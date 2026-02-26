from fpdf import FPDF
import os
import random

# Create a folder for the resumes if it doesn't exist
if not os.path.exists("test_resumes"):
    os.makedirs("test_resumes")

class ResumePDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, 'Resume Content', 0, 1, 'R')
        self.ln(2)

    def add_resume_section(self, title, body):
        self.set_font('Arial', 'B', 14)
        self.set_fill_color(230, 230, 230) # Light gray background for headers
        self.cell(0, 8, title, 0, 1, 'L', 1)
        self.ln(2)
        self.set_font('Arial', '', 10) # Slightly smaller font to fit dense info
        # Replace unsupported characters to avoid FPDF latin-1 errors
        clean_body = body.replace('•', '-').replace('\u2013', '-').replace('\u2019', "'")
        self.multi_cell(0, 5, clean_body)
        self.ln(4)

def create_pdf(filename, name, contact, education, experience, projects, skills):
    pdf = ResumePDF()
    pdf.add_page()
    
    # 1. Header (Name & Contact)
    pdf.set_font('Arial', 'B', 20)
    pdf.cell(0, 10, name, 0, 1, 'C')
    pdf.set_font('Arial', '', 10)
    pdf.cell(0, 5, contact, 0, 1, 'C')
    pdf.ln(8)
    
    # 2. Sections
    pdf.add_resume_section("EDUCATION", education)
    pdf.add_resume_section("PROFESSIONAL EXPERIENCE", experience)
    pdf.add_resume_section("PROJECTS", projects)
    pdf.add_resume_section("TECHNICAL SKILLS", skills)
    
    # 3. Save
    filepath = f"test_resumes/{filename}"
    pdf.output(filepath)
    print(f"✅ Created: {filepath}")

# --- DATA POOLS FOR DYNAMIC GENERATION ---

first_names = ["Alex", "Jordan", "Casey", "Taylor", "Morgan", "Sam", "Jamie", "Riley", "Avery", "Quinn", "Ibrahim", "Sarah", "Omar", "Zain", "Fatima"]
last_names = ["Smith", "Mercer", "Lee", "Zubairi", "Khan", "Ahmed", "Chen", "Patel", "Gupta", "Williams", "Davis", "Tariq", "Ali", "Hasan"]

universities = [
    "Karachi School of Business and Leadership\nBachelors in Computer Science | Sept 2023 - June 2027",
    "University of Technology\nB.S. in Software Engineering | Aug 2020 - May 2024",
    "Global Tech Institute\nB.S. in Artificial Intelligence | Jan 2021 - Dec 2025"
]

roles = ["AI Engineering Intern", "Co-Founder & CTO", "Senior Backend Developer", "Full-Stack Engineer", "Machine Learning Engineer"]
companies = ["Salesflo", "LoqAI", "TechStream", "DataFlow Systems", "VisionaryAI", "CyberNet"]

# High-density, metric-driven bullet points mimicking your resume
exp_bullets = [
    "- Engineered a WhatsApp-based AI distributor agent for retail stores, migrating end-to-end workflows from Make.com to Google Agentic Development Kit (ADK) with Vertex AI, reducing operational latency by 35%.",
    "- Developed and optimized multi-agent orchestration using A2A protocol and advanced prompt engineering, improving agent decision accuracy by 20% in SKU selection and manual ordering workflows.",
    "- Leading development of a full-stack HR Management & Payroll System with attendance, leave workflows, onboarding, and automated payroll generation.",
    "- Engineering seamless third-party accounting integrations to sync payroll, ledgers, expenses, and financial reports in real time.",
    "- Building an AI-powered ATS capable of resume parsing, candidate ranking, and recruiter-style LLM explanations.",
    "- Architected a secure, scalable multi-tenant SaaS using FastAPI, React, PostgreSQL, JWT auth, and cloud-native deployment.",
    "- Managed high-performance relational databases, writing complex stored procedures and triggers to eliminate SQL injection risks across 15+ tables.",
    "- Automated retail distribution workflows with Google ADK tools, integrating SKU recommender, cutting manual intervention time by 40%."
]

project_titles = [
    "Airline Reservation System (Java, Swing, JDBC, MSSQL)",
    "AutoLog Smart Car Management App (Java, MySQL)",
    "AI-Powered Applicant Tracking System (Python, FastAPI, Gemini LLM)",
    "FinTech Payroll Ledger (React, Node.js, PostgreSQL)",
    "Retail Distribution Bot (Vertex AI, LangChain, Python)"
]

project_bullets = [
    "- Built a role-based system with flight search, booking, payments, and admin controls improving workflow efficiency by 40% through stored procedures.",
    "- Engineered secure, modular DB interactions using transactions and RBAC, ensuring data integrity.",
    "- Developed an intuitive GUI supporting User, Admin, and Super Admin roles with dynamic state management.",
    "- Developing a MySQL-backed mobile app for vehicle maintenance, fuel logging, and diagnostics.",
    "- Engineering an Arduino-integrated GPS tracker to automate fuel stop detection via Bluetooth/Wi-Fi.",
    "- Implementing an AI-driven diagnostics module for issue classification and repair recommendations.",
    "- Designed a RESTful API to handle 10,000+ daily concurrent requests with 99.9% uptime."
]

skills_blocks = [
    "Programming Languages: Java, Python, SQL, C++\nAI & Agentic Systems: Google ADK, Multi-Agent Orchestration, Tool-Calling LLMs, Prompt Engineering, Make.com, LangChain\nAI Platforms: Vertex AI, Google Colab, OpenAI API\nBackend: Spring Boot, FastAPI, Django\nDatabases: PostgreSQL, MSSQL, MySQL",
    "Programming Languages: JavaScript, TypeScript, Python, SQL\nFrontend: React, Next.js, Tailwind CSS\nBackend: Node.js, Express, FastAPI\nCloud & DevOps: AWS (EC2, S3), Docker, GitHub Actions\nData Science: Pandas, NumPy",
    "Programming Languages: Python, R, SQL, Java\nAI & ML: TensorFlow, PyTorch, Scikit-learn, Regression, Classification\nData Engineering: Apache Spark, Airflow, Hadoop\nCloud Platforms: Google Cloud Platform (GCP), Vertex AI"
]

# --- GENERATOR LOOP ---

def generate_resumes(count=20):
    for i in range(1, count + 1):
        # Generate Name & Contact
        name = f"{random.choice(first_names)} {random.choice(last_names)}"
        contact = f"+92-300-0000{i:03d} | {name.lower().replace(' ', '.')}@gmail.com | github.com/{name.lower().split()[0]}"
        
        # Select Education
        education = random.choice(universities)
        
        # Generate Experience (2 Jobs per resume)
        experience = ""
        for _ in range(2):
            role = random.choice(roles)
            company = random.choice(companies)
            duration = f"{random.choice(['Jan', 'Mar', 'Jun', 'Sept'])} 202{random.randint(1,3)} - Present"
            experience += f"{role} | {company} | {duration}\n"
            # Pick 3 random, unique bullets
            bullets = random.sample(exp_bullets, 3)
            experience += "\n".join(bullets) + "\n\n"
            
        # Generate Projects (2 Projects per resume)
        projects = ""
        for _ in range(2):
            title = random.choice(project_titles)
            projects += f"{title}\n"
            bullets = random.sample(project_bullets, 2)
            projects += "\n".join(bullets) + "\n\n"
            
        # Select Skills
        skills = random.choice(skills_blocks)
        
        # Create PDF
        filename = f"resume_{i:02d}_{name.replace(' ', '_')}.pdf"
        create_pdf(filename, name, contact, education, experience.strip(), projects.strip(), skills)

# Execute the generator
generate_resumes(20)
print("\n🎉 Successfully generated 20 highly-detailed test resumes in the 'test_resumes' folder!")