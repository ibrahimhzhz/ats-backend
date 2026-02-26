"""
Test script for the Multi-Stage Bulk Screening Pipeline
Tests all 4 stages: Knockouts, AI Evaluation, Weighted Scoring, DB Persistence
"""
import requests
import time
import json
from pathlib import Path

# Configuration
BASE_URL = "http://localhost:8001"
API_ENDPOINT = f"{BASE_URL}/api/bulk-screen"
STATUS_ENDPOINT = f"{BASE_URL}/api/job"

def test_bulk_screening():
    """
    Test the complete multi-stage pipeline with a sample job.
    """
    print("=" * 70)
    print("🧪 TESTING MULTI-STAGE ATS PIPELINE")
    print("=" * 70)
    
    # Step 1: Prepare test data
    print("\n📋 Step 1: Preparing Test Data")
    print("-" * 70)
    
    job_description = """
    Senior Backend Engineer
    
    We're looking for an experienced backend engineer to join our team.
    You'll be building scalable APIs and working with cloud infrastructure.
    
    Requirements:
    - 5+ years of Python development
    - Strong experience with FastAPI, Django, or Flask
    - Experience with PostgreSQL or MySQL
    - Cloud experience (AWS, GCP, or Azure)
    - Docker and Kubernetes experience
    - RESTful API design
    """
    
    min_experience = 5.0
    required_skills = "Python,FastAPI,PostgreSQL,Docker,AWS"
    
    print(f"   Job: Senior Backend Engineer")
    print(f"   Min Experience: {min_experience} years")
    print(f"   Required Skills: {required_skills}")
    
    # Step 2: Check if resumes ZIP exists
    print("\n📦 Step 2: Checking for Test Resumes")
    print("-" * 70)
    
    zip_path = Path("test_resumes.zip")
    if not zip_path.exists():
        # Try alternative path
        zip_path = Path("test_resumes")
        if zip_path.exists() and zip_path.is_dir():
            print(f"   ⚠️  Found folder: {zip_path}")
            print(f"   💡 Create a ZIP file from your test_resumes folder:")
            print(f"      Compress-Archive -Path 'test_resumes\\*.pdf' -DestinationPath 'test_resumes.zip'")
            return
        else:
            print("   ❌ No test_resumes.zip or test_resumes/ folder found")
            print("   💡 Place sample PDF resumes in a test_resumes.zip file")
            return
    
    print(f"   ✅ Found: {zip_path}")
    
    # Step 3: Submit bulk screening request
    print("\n🚀 Step 3: Submitting Bulk Screening Request")
    print("-" * 70)
    
    try:
        with open(zip_path, 'rb') as zip_file:
            files = {'resumes_zip': ('test_resumes.zip', zip_file, 'application/zip')}
            data = {
                'job_description': job_description,
                'min_experience': str(min_experience),
                'required_skills': required_skills
            }
            
            print(f"   Sending POST to {API_ENDPOINT}")
            response = requests.post(API_ENDPOINT, files=files, data=data)
            
            if response.status_code != 200:
                print(f"   ❌ Request failed: {response.status_code}")
                print(f"   Response: {response.text}")
                return
            
            result = response.json()
            job_id = result.get('job_id')
            db_job_id = result.get('db_job_id')
            total_resumes = result.get('total_resumes')
            
            print(f"   ✅ Request accepted!")
            print(f"   Job ID: {job_id}")
            print(f"   Database Job ID: {db_job_id}")
            print(f"   Total Resumes: {total_resumes}")
    
    except FileNotFoundError:
        print(f"   ❌ Could not open {zip_path}")
        return
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return
    
    # Step 4: Poll for results
    print("\n⏳ Step 4: Monitoring Progress")
    print("-" * 70)
    
    max_wait_time = 300  # 5 minutes
    poll_interval = 2    # Check every 2 seconds
    elapsed_time = 0
    
    while elapsed_time < max_wait_time:
        try:
            status_response = requests.get(f"{STATUS_ENDPOINT}/{job_id}")
            
            if status_response.status_code != 200:
                print(f"   ❌ Could not fetch status: {status_response.status_code}")
                break
            
            job_status = status_response.json()
            status = job_status.get('status')
            processed = job_status.get('processed', 0)
            total = job_status.get('total_resumes', 0)
            
            progress_pct = (processed / total * 100) if total > 0 else 0
            
            print(f"   Status: {status.upper()} | Progress: {processed}/{total} ({progress_pct:.0f}%)", end='\r')
            
            if status == 'completed':
                print("\n   ✅ Processing completed!")
                
                # Display results
                print("\n📊 Step 5: Results Summary")
                print("-" * 70)
                
                results = job_status.get('results', {})
                
                print(f"   Total Processed: {results.get('total_processed', 0)}")
                print(f"   Knocked Out (Rule-based): {results.get('knocked_out', 0)} 🚫")
                print(f"   AI Evaluated: {results.get('ai_evaluated', 0)} 🤖")
                print(f"   ")
                print(f"   Final Results:")
                print(f"   - Shortlisted (80+): {results.get('shortlisted_count', 0)} ✅")
                print(f"   - Review (60-79): {results.get('review_count', 0)} ⚠️")
                print(f"   - Rejected (<60): {results.get('rejected_count', 0)} ❌")
                
                # Display criteria
                criteria = results.get('criteria', {})
                print(f"\n   Criteria Applied:")
                print(f"   - Min Experience: {criteria.get('min_experience')} years")
                print(f"   - Required Skills: {', '.join(criteria.get('required_skills', []))}")
                
                # Show top candidates
                shortlisted = results.get('shortlisted', [])
                if shortlisted:
                    print(f"\n   🌟 Top Shortlisted Candidates:")
                    for i, candidate in enumerate(shortlisted[:5], 1):
                        print(f"   {i}. {candidate.get('name')} - Score: {candidate.get('match_score'):.1f}")
                        print(f"      Email: {candidate.get('email')}")
                        print(f"      Experience: {candidate.get('years_experience')} years")
                        print(f"      Summary: {candidate.get('summary', '')[:80]}...")
                        print()
                else:
                    print(f"\n   ⚠️  No candidates met the shortlist criteria (score >= 80)")
                
                # Token savings calculation
                knocked_out = results.get('knocked_out', 0)
                ai_evaluated = results.get('ai_evaluated', 0)
                total_candidates = results.get('total_processed', 0)
                
                if knocked_out > 0:
                    token_savings = (knocked_out / total_candidates * 100) if total_candidates > 0 else 0
                    print(f"\n   💰 Token Savings:")
                    print(f"   Saved {knocked_out * 2} LLM calls by knockout filtering")
                    print(f"   ({token_savings:.0f}% reduction in API costs)")
                
                break
            
            elif status == 'failed':
                print("\n   ❌ Processing failed!")
                error = job_status.get('error')
                if error:
                    print(f"   Error: {error}")
                break
            
            time.sleep(poll_interval)
            elapsed_time += poll_interval
        
        except KeyboardInterrupt:
            print("\n\n   ⚠️  Interrupted by user")
            break
        except Exception as e:
            print(f"\n   ❌ Error polling status: {e}")
            break
    
    if elapsed_time >= max_wait_time:
        print("\n   ⏰ Timeout: Processing is taking longer than expected")
        print(f"   You can check status manually at: {STATUS_ENDPOINT}/{job_id}")
    
    print("\n" + "=" * 70)
    print("✅ TEST COMPLETE")
    print("=" * 70)
    print(f"\n💡 View all applicants in database with Job ID: {db_job_id}")
    print(f"   Query: SELECT * FROM applicants WHERE job_id = {db_job_id};")


def test_health_check():
    """Quick health check of the API"""
    print("\n🏥 Health Check")
    print("-" * 70)
    try:
        response = requests.get(f"{BASE_URL}/api/health")
        if response.status_code == 200:
            print("   ✅ API is running")
            return True
        else:
            print(f"   ❌ API returned status {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"   ❌ Could not connect to {BASE_URL}")
        print("   💡 Make sure the server is running:")
        print("      uvicorn main:app --reload --port 8001")
        return False


if __name__ == "__main__":
    # Check if server is running
    if test_health_check():
        # Run the bulk screening test
        test_bulk_screening()
    else:
        print("\n⚠️  Cannot proceed without API connection")
