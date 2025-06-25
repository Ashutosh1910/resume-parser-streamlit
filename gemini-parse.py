import streamlit as st
import os
import json
import textwrap
import sqlite3
import pandas as pd
import google.generativeai as genai
from dotenv import load_dotenv
from pdfminer.high_level import extract_text
import docx
import re
UPLOAD_DIR = 'uploaded_resumes'
os.makedirs(UPLOAD_DIR, exist_ok=True)
def get_phone(text):
    phone_regex = re.compile(r'''
        (?:(?:\+?\d{1,3}[\s\-]?)?(?:\(?\d{3,5}\)?[\s\-]?)?)? 
        \d{3,5}[\s\-]?\d{3,5}(?:[\s\-]?\d{3,5})?              
    ''', re.VERBOSE)

    matches = phone_regex.findall(text)
    for match in matches:
        digits = re.sub(r'\D', '', match)
        if 10 <= len(digits) <= 13:
            return match.strip()
    return None
def get_email(text):
    match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', text)
    return match.group(0) if match else None
def init_db():
    conn = sqlite3.connect('resume_data.db')
    c = conn.cursor()
    # Updated schema to include name, email, and the path to the saved file
    c.execute('''
        CREATE TABLE IF NOT EXISTS resumes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            name TEXT,
            email TEXT,
            saved_filepath TEXT,
            parsed_json TEXT NOT NULL,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def add_resume_to_db(filename, parsed_data, file_bytes):
    conn = sqlite3.connect('resume_data.db')
    c = conn.cursor()

    # Extract name and email for easy access, with fallbacks
    person_name = parsed_data.get('personal_info', {}).get('name', 'N/A')
    person_email = parsed_data.get('personal_info', {}).get('email', 'N/A')
    json_string = json.dumps(parsed_data)

    c.execute(
        "INSERT INTO resumes (filename, name, email, parsed_json) VALUES (?, ?, ?, ?)",
        (filename, person_name, person_email, json_string)
    )
    resume_id = c.lastrowid

    saved_filepath = os.path.join(UPLOAD_DIR, f"resume_{resume_id}.pdf" if filename.endswith('.pdf') else 'resume_{resume_id}.docx')

    # Save the actual file
    with open(saved_filepath, 'wb') as f:
        f.write(file_bytes)

    # Update the record with the path to the saved file
    c.execute("UPDATE resumes SET saved_filepath = ? WHERE id = ?", (saved_filepath, resume_id))

    conn.commit()
    conn.close()

def get_all_resumes():
    conn = sqlite3.connect('resume_data.db')
    c = conn.cursor()
    c.execute("SELECT id, filename, name, parsed_json, uploaded_at, saved_filepath FROM resumes ORDER BY uploaded_at DESC")
    records = c.fetchall()
    conn.close()
    return records

def get_text_from_docx(path):
    doc = docx.Document(path)
    return '\n'.join([para.text for para in doc.paragraphs])

def extract_text_from_file(uploaded_file):
   if uploaded_file.name.endswith('.pdf'):
        return extract_text(uploaded_file)
   else:
       return get_text_from_docx(uploaded_file)
        

def get_gemini_response(resume_text, api_key):
    genai.configure(api_key=api_key)
    prompt = textwrap.dedent(f"""
        You are an expert resume parser. Your task is to analyze the provided resume text and extract key information into a structured JSON format.

        The JSON object must have the following top-level keys: "personal_info", "Skills", "Education", "Work Experience", and "Projects".

        Follow this specific schema:
        {{
          "personal_info": {{
            "name": "Candidate's Full Name",
          }},
          "Skills": [
            "Skill 1", "Skill 2", ...
          ],
          "Education": [
            {{
              "institution": "University Name",
              "degree": "Degree (e.g., Bachelor of Science in Computer Science)",
              "Grade": "Grade or GPA",
              "graduation_date": "Month Year (e.g., May 2020)",
              "location": "City, State"
            }}
          ],
          "Work Experience": [
            {{
              "company": "Company Name",
              "job_title": "Your Title",
              "start_date": "Month Year",
              "end_date": "Month Year or 'Present'",
              "location": "City, State",
              "responsibilities": [
                "A bullet point describing a key achievement or responsibility.",
                "Another bullet point."
              ]
            }}
          ],
          "Projects": [
            {{
              "name": "Project Name",
              "description": "A brief description of the project.",
              "technologies": ["Tech 1", "Tech 2"],
              "link": "URL to the project if available"
            }}
          ]
        }}

        Important Rules:
        1. The entire output MUST be a single, valid JSON object. Do not include any text, explanations, or markdown formatting like ```json before or after the JSON.
        2. If a section (like "Projects") or a field (like "phone") is not found, its value should be an empty array `[]` or `null`, respectively.
        3. Extract the candidate's full name and email accurately into the `personal_info` object.

        Analyze the following resume text and generate the JSON:
        --- RESUME TEXT START ---
        {resume_text}
        --- RESUME TEXT END ---
    """)

    model = genai.GenerativeModel('gemini-2.0-flash')
    response = model.generate_content(prompt)
    cleaned_json_string = response.text.strip().replace('```json', '').replace('```', '').strip()
    return cleaned_json_string

def display_parsed_data_in_tables(data):
    """Displays the parsed JSON data in a structured, tabular format."""
    # Personal Info and Skills
    st.subheader("👤 Personal Information")
    info = data.get("personal_info", {})
    if info:
        st.write(f"**Name:** {info.get('name', 'N/A')}")
        st.write(f"**Email:** {info.get('email', 'N/A')}")
        st.write(f"**Phone:** {info.get('phone', 'N/A')}")

    st.subheader("Skills")
    skills = data.get("Skills", [])
    if skills:
        st.write(", ".join(skills))
    else:
        st.write("No skills found.")

    st.subheader("Education")
    education = data.get("Education", [])
    if education:
        df_edu = pd.DataFrame(education)
        st.dataframe(df_edu, use_container_width=True)
    else:
        st.write("No education details found.")

    st.subheader("Work Experience")
    experience = data.get("Work Experience", [])
    if experience:
        df_exp = pd.DataFrame(experience)
        df_exp['responsibilities'] = df_exp['responsibilities'].apply(lambda x: "\n".join(f"- {item}" for item in x) if isinstance(x, list) else x)
        st.dataframe(df_exp, use_container_width=True)
    else:
        st.write("No work experience found.")

    st.subheader("Projects")
    projects = data.get("Projects", [])
    if projects:
        df_proj = pd.DataFrame(projects)
        df_proj['technologies'] = df_proj['technologies'].apply(lambda x: ', '.join(x) if isinstance(x, list) else x)
        st.dataframe(df_proj, use_container_width=True)
    else:
        st.write("No projects found.")


def main():
    load_dotenv()
    st.set_page_config(page_title="Resume Parser", layout="wide", initial_sidebar_state="expanded")
    init_db()

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        st.error("Google API Key not found! Please set it in your .env file.")
        st.stop()

    st.title("Resume Parser")
    st.write("Upload a resume (PDF or docx)")

    uploaded_file = st.file_uploader("Choose a PDF or a DOCX file", type=["pdf","docx"])

    if uploaded_file is not None:
        if st.button(f"Parse '{uploaded_file.name}'"):
            with st.spinner('Parsing in progress... This may take a moment.'):
                try:
                    file_bytes = uploaded_file.getvalue()
                    resume_text = extract_text_from_file(uploaded_file)
                    gemini_output_str = get_gemini_response(resume_text, api_key)

                    parsed_json = json.loads(gemini_output_str)
                    parsed_json['personal_info']['email']=get_email(resume_text) if get_email(resume_text) else 'NOT FOUND'
                    parsed_json['personal_info']['phone']=get_phone(resume_text) if get_phone(resume_text) else 'NOT FOUND'
                    add_resume_to_db(uploaded_file.name, parsed_json, file_bytes)

                    st.success("Resume parsed and saved successfully!")
                    display_parsed_data_in_tables(parsed_json)

                except json.JSONDecodeError:
                    st.error("Failed to parse the AI's response as JSON. The raw response was:")
                    st.text(gemini_output_str)
                except Exception as e:
                    st.error(f"An unexpected error occurred: {e}")

    st.sidebar.title("Parsing History")
    history_records = get_all_resumes()

    if not history_records:
        st.sidebar.info("No resumes have been parsed yet.")
    else:
        for record in history_records:
            record_id, filename, name, json_data, timestamp, saved_filepath = record
            
            # Use candidate's name for the expander, fallback to filename
            display_name = name if name and name != 'N/A' else filename
            
            with st.sidebar.expander(f"**{display_name}** `({timestamp.split(' ')[0]})`"):
                if saved_filepath and os.path.exists(saved_filepath):
                    with open(saved_filepath, "rb") as file:
                        st.download_button(
                            label="Download Original Resume",
                            data=file.read(),
                            file_name=filename, 
                            mime="application/octet-stream",
                            key=f"download_{record_id}" 
                        )
                
                data = json.loads(json_data)
                display_parsed_data_in_tables(data)


if __name__ == "__main__":
    main()