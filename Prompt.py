import datetime

def get_dynamic_prompt():
    """
    Generate a prompt with dynamically calculated year values for expected graduation.
    Updates the prompt to handle 'current', 'present', or 'now' in education entries.
    """
    # Get current year only (not calculating next year anymore)
    current_year = datetime.datetime.now().year

    # Create the dynamic prompt with updated graduation year guidance
    prompt = f"""TASK: Extract structured information from CV documents with high precision and consistency.

IMPORTANT INSTRUCTIONS:
- Process each CV separately, identifying clear boundaries between different individuals.
- For each person, extract EXACTLY the 10 fields specified below.
- Double-check all extracted information for accuracy.
- Only include information that appears at least twice in the document or has strong supporting evidence.
- If information cannot be verified with high confidence or values don't match across checks, use "N/A" instead of guessing.
- Return data in a structured JSON array format, with one object per person.
- Do NOT include any explanatory text, headers, or additional formatting beyond valid JSON.

EXTRACTION FIELDS (10 required fields):

1. FIRST_NAME
   - Extract only the given/first name.
   - Verify spelling carefully.
   - If multiple first names, use only the first one.
   - Example: "John" from "John William Smith".

2. LAST_NAME
   - Extract only the family/last name.
   - Include all parts of compound surnames.
   - Example: "Smith-Johnson" should be kept as is.

3. EMAIL
   - Must follow standard email format (name@domain.tld).
   - Verify the domain exists (common domains: gmail.com, outlook.com, student.university.edu).
   - If no valid email is found, use "N/A".

4. PHONE_NUMBER
   - Include country code if available.
   - Standardize format if possible.
   - If no phone number is found, use "N/A".
   - If multiple phone numbers are found, use the one that starts with the country cod +32 or 04 or 4 (belgium). 

5. EDUCATION_LEVEL
   - STRICT HIERARCHY: Master > Academic Bachelor > Professional Bachelor > Secondary level.
   - "Master" - ANY master's degree (ongoing or completed).
   - "Academic Bachelor" - ONLY university bachelor's degrees.
   - "Professional Bachelor" - Non-university bachelor's degrees (colleges, institutes).
   - "Secondary level" - High school or equivalent.
   - Double-check educational institutions to correctly classify university vs. non-university.

6. EXPECTED_GRADUATION_YEAR
   - Format: 4-digit year (e.g., "{current_year}").
   - ONLY for the most recent educational program.
   - Use the year of the expected graduation, so the latest year of the program.
   - Must be EXPLICITLY stated in the document.
   - IMPORTANT: When you see "Present", "Now", "Current", or any variation (like "2023 - Present")
     in the education timeline, use "{current_year}" as the expected graduation year.
   - For standard educational programs with "current" or "present" status:
     * Bachelor's programs: typically add 3 years from the start date.
     * Master's programs: typically add 1-2 years from the start date.
   - If no information is found, use "N/A".

7. FACULTY
   - STRICTLY categorize into these fields ONLY:
   - Choose the facutly of the latest program, to achieve this use this logic: STRICT HIERARCHY: Master > Academic Bachelor > Professional Bachelor > Secondary level.
   - So most of the time it will be the faculty of the master program.
   - If no master program is found, then choose the faculty of the bachelor program.
   - If no bachelor program is found, then choose the faculty of the professional bachelor program.
   - If no professional bachelor program is found, then choose the faculty of the secondary level program.
   - If no secondary level program is found, then use "N/A".
   - YOU MUST CHOOSE ONE OF THE FOLLOWING 8 FACULTIES:
     OTHER IS NOT ACCEPTED.

      * "Arts & Philosophy"
        - Humanities, history, literature, linguistics, philosophy
        - Fine arts, visual arts, performing arts, music, theater
        - Cultural studies, religious studies, classics
        - Translation, interpretation studies
        - Archaeology, anthropology (cultural)

      * "Economics & business"
        - Business engineering (handelsingenieur, ingénieur de gestion)
        - Economics, applied economics, econometrics
        - Finance, accounting, actuarial studies
        - Marketing, business administration
        - International trade, international business
        - Commercial engineering, commercial sciences

      * "Management"
        - Any degree with "management" in the title
        - Project management, operations management
        - Supply chain management, logistics management
        - Human resource management
        - Hotel management, tourism management
        - Public management, non-profit management

      * "Engineering & Technology"
        - All engineering disciplines EXCEPT business engineering
        - Computer science, informatics, IT
        - Electrical, civil, mechanical, chemical engineering
        - Biotechnology (technical focus)
        - Architecture, urban planning
        - Data science (technical focus)

      * "Social Sciences"
        - Sociology, psychology, political science
        - Communication studies, media studies
        - Educational sciences, pedagogy
        - Social work, public policy
        - International relations, development studies
        - Anthropology (social)

      * "Law & Criminology"
        - Law, legal studies, jurisprudence
        - Criminology, criminal justice
        - International law, European law
        - Tax law, business law
        - Notary studies

      * "Science"
        - Physics, chemistry, biology, geology
        - Mathematics, statistics
        - Biochemistry, bioscience (non-medical)
        - Environmental science, geography
        - Astronomy, marine science
        - Data science (research-oriented)

      * "Health Sciences"
        - Medicine, dentistry, pharmacy
        - Nursing, midwifery, paramedical studies
        - Physical therapy, occupational therapy
        - Public health, health management
        - Veterinary medicine
        - Biomedical sciences

   * Verification techniques:
     - Cross-reference degree title with department/faculty name.
     - Check course descriptions if available.
     - Consider the degree-granting institution's specialization.
     - For ambiguous cases, check thesis topic or specialization.

8. NATIVE_LANGUAGE
   - Location: Focus on the "Skills" or "Languages" section of the CV.
   - Indicators: Look for terms like "Mother tongue," "Native," or "C2 level" to identify the native language.
   - Acceptable Languages: Only accept "Dutch," "French," "English.
   - Make sure to accept only: "Dutch", "French", "English",!!!!!!! -> You need to convert other languages to "Other"!!!!
   - If the language is not "Dutch", "French", "English", then use "Other."
   - Proficiency Level: Note that C1 level is not sufficient for native classification; only C2 or explicit terms like "Native" or "Mother tongue" are acceptable.

   Examples:
   - English (Native): Accept as "English."
   - French (Mother tongue): Accept as "French."
   - Dutch (C2 level): Accept as "Dutch."
   - Spanish (C2 level): Classify as "Other."  (other languages then English, Dutch, French are converted to "Other")
   - Urdu (Native): Classify as "Other." (other languages then English, Dutch, French are converted to "Other")

   Tips for Accuracy:
   - Keywords: Search for keywords such as "Native speaker," "Fluent," or "Bilingual" in conjunction with the language.
   - Context: Consider the context in which the language is mentioned. For example, if a candidate mentions being raised in a specific country, their native language might align with that country.
   - Consistency: Ensure consistency in classification by adhering strictly to the criteria provided.

9. LINKEDIN_PROFILE_URL
   - Location: Check the contact section, header, footer, or social media section of the CV.
   - Priority: Look specifically for a LinkedIn profile link first ("LinkedIn:"). If not found, then consider other professional networking platforms.
   - Valid Platforms: LinkedIn, Wefynd, Karamel, Shortlist, or personal websites. Always prioritize LinkedIn over other platforms.
   - URL Requirement: Ensure the URL is complete and includes the http:// or https:// prefix.
   - Identification: Look for icons or text that indicate professional networking sites, such as the LinkedIn logo or the word "LinkedIn."
   - Examples:
     - LinkedIn: https://www.linkedin.com/in/username
     - Wefynd: https://wefynd.com/profile/username
     - Personal Website: https://www.username.com

10. POTENTIAL_INTEREST
   - You must categorize each candidate into EXACTLY ONE of these SIX categories:
     * "Management"
     * "Sustainability"
     * "Data"
     * "Finance"
     * "IT/AI"
     * "Supply Chain"
   - Base your classification on a comprehensive analysis of:
     * Academic degrees and educational focus
     * Work experience and internships
     * Hard skills listed in the CV
     * Soft skills that indicate specific interests
     * Projects, thesis topics, or research interests
     * Extracurricular activities, volunteer work
     * Stated career goals or objectives
   - Classification Guidelines:
     * "Management": Leadership roles, project management, business administration, organizational skills, team coordination, HR activities
     * "Sustainability": Environmental studies, renewable energy, CSR activities, climate-related projects, circular economy, eco-friendly initiatives 
     * "Data": Data analysis, statistics, mathematics, data visualization, research methodology, market research, business intelligence, programming languages, software development, digital transformation, artificial intelligence, machine learning, tech projects
     * "Finance": Accounting, investment activities, banking experience, financial planning, risk assessment, budget management, financial modeling, investment banking, asset management, insurance, risk management
     * "IT/AI": Programming languages, software development, digital transformation, artificial intelligence, machine learning, tech projects, data science, data engineering, data analysis, data visualization, research methodology, market research, business intelligence
     * "Supply Chain": Logistics, operations, procurement, inventory management, distribution, manufacturing processes, global trade, supply chain management, supply chain optimization, supply chain logistics, supply chain planning, supply chain coordination, supply chain integration, supply chain risk management, supply chain sustainability, supply chain innovation, supply chain optimization, supply chain coordination, supply chain integration, supply chain risk management, supply chain sustainability, supply chain innovation
    Since Data and IT/AI are very similar, make sure to choose the category that best aligns with the candidate's interests and skills. Lean more towards Data if the candidate has a strong background in data analysis and programming. Otherwise, choose IT/AI if the candidate has a strong background in software development and artificial intelligence.
     
   - Decision Hierarchy:
     * Prioritize explicit statements about career interests or goals
     * Then consider actual work experience and internships
     * Then analyze skills and technical knowledge
     * Then evaluate educational background and specializations

   - If there are multiple potential interests, choose the one with the strongest evidence.
   - If there's insufficient evidence to make a determination, choose the category that best aligns with their faculty.
   - Always select one of the six options - "N/A" is not acceptable for this field.

SPECIAL CONTENT HANDLING:
- MULTILINGUAL DOCUMENTS: Extract data in the document's primary language, then translate field values to English.
- TABLES/CHARTS: Carefully examine for education history, work experience, or skill metrics.
- SCANNED DOCUMENTS: Watch for image quality issues affecting text recognition.
- LOGOS/ICONS: Use these as contextual clues for education institutions or professional platforms.

ADVANCED EXTRACTION TECHNIQUES:
- Use chronological analysis for education/career progression.
- Cross-reference contact information with name spelling.
- Use section headings as contextual guides (e.g., "Work Experience," "Education").
- When encountering inconsistencies, prioritize information from formal sections over casual mentions.

CV BOUNDARY RECOGNITION:
- Files often combine multiple CVs without clear separation.
- Key indicators of a new CV: new personal details section, page number resetting, distinct formatting changes.
- Watch for header text like "CV," "Resume," or "Curriculum Vitae" followed by a new name.
- Different document templates or styling often indicate a new person.

QUALITY ASSURANCE:
- VERIFY ALL EXTRACTIONS against multiple mentions in the document.
- For ambiguous cases, choose "N/A" rather than guessing.
- Ensure categorizations follow the strict hierarchies provided.
- Maintain consistency in field names and formatting.

OUTPUT FORMAT:
Return data as a valid JSON array where each object represents one person with the following format:
```json
[
  {{
    "FIRST_NAME": "...",
    "LAST_NAME": "...",
    "EMAIL": "...",
    "PHONE_NUMBER": "...",
    "EDUCATION_LEVEL": "...",
    "EXPECTED_GRADUATION_YEAR": "...",
    "FACULTY": "...",
    "NATIVE_LANGUAGE": "...",
    "LINKEDIN_PROFILE_URL": "...",
    "POTENTIAL_INTEREST": "..."
  }},
  {{
    "FIRST_NAME": "...",
    "LAST_NAME": "...",
    ...
  }}
]
```
Ensure the JSON is valid and properly formatted. Do not include any text before or after the JSON array.
"""
    return prompt

# Generate the dynamic prompt when this module is imported
master_prompt = get_dynamic_prompt()

# This allows manual regeneration of the prompt if needed
def refresh_prompt():
    """Regenerate the master prompt with current date information"""
    global master_prompt
    master_prompt = get_dynamic_prompt()
    return master_prompt

if __name__ == "__main__":
    print(get_dynamic_prompt())
