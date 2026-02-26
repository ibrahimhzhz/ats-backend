"""Quick script to check applicants in database"""
import sqlite3

conn = sqlite3.connect('ats.db')
cursor = conn.cursor()

# Check applicants for job 13
print("=== Checking Applicants for Job 13 ===")
cursor.execute("""
    SELECT id, job_id, company_id, name, email, match_score, status, created_at
    FROM applicants 
    WHERE job_id = 13
    ORDER BY id DESC
""")
applicants = cursor.fetchall()
print(f"Found {len(applicants)} applicants:")
for row in applicants:
    print(f"  ID: {row[0]}, Company: {row[2]}, Name: {row[3]}, Email: {row[4]}, Score: {row[5]}, Status: {row[6]}")

# Check all applicants
print("\n=== All Applicants ===")
cursor.execute("SELECT id, job_id, company_id, name, email FROM applicants ORDER BY id DESC LIMIT 5")
all_applicants = cursor.fetchall()
print(f"Latest 5 applicants:")
for row in all_applicants:
    print(f"  ID: {row[0]}, Job: {row[1]}, Company: {row[2]}, Name: {row[3]}, Email: {row[4]}")

# Check job 13
print("\n=== Job 13 Details ===")
cursor.execute("SELECT id, company_id, title, views, application_count FROM jobs WHERE id = 13")
job = cursor.fetchone()
if job:
    print(f"Job ID: {job[0]}, Company: {job[1]}, Title: {job[2]}, Views: {job[3]}, Applications: {job[4]}")
else:
    print("Job 13 not found")

# Check users
print("\n=== Users ===")
cursor.execute("SELECT id, company_id, email FROM users")
users = cursor.fetchall()
for row in users:
    print(f"User ID: {row[0]}, Company: {row[1]}, Email: {row[2]}")

conn.close()
