import streamlit as st
import requests
import pandas as pd
import json
from datetime import datetime
import base64
from io import BytesIO
import os
from dotenv import load_dotenv
from enums import Project, WorkItemType, IterationPath
import urllib3

# Suppress SSL warnings when verification is disabled
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Load environment variables
load_dotenv('../.env')

# Page configuration
st.set_page_config(
    page_title="Project Report Generator",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for clean, modern styling
st.markdown("""
<style>
    .main-header {
        text-align: center;
        color: #1f77b4;
        margin-bottom: 2rem;
        font-size: 2.5rem;
        font-weight: bold;
    }
    
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 1rem;
        border-radius: 10px;
        text-align: center;
        margin: 0.5rem;
    }
    
    .metric-value {
        font-size: 2rem;
        font-weight: bold;
        margin-bottom: 0.5rem;
    }
    
    .metric-label {
        font-size: 0.9rem;
        opacity: 0.9;
    }
    
    .stButton > button {
        background: linear-gradient(45deg, #667eea, #764ba2);
        color: white;
        border: none;
        border-radius: 10px;
        padding: 0.75rem 1.5rem;
        font-weight: bold;
        font-size: 1.1rem;
        transition: all 0.3s ease;
    }
    
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
    }
    
    .success-box {
        background: #d4edda;
        border: 1px solid #c3e6cb;
        border-radius: 5px;
        padding: 1rem;
        margin: 1rem 0;
        color: #155724;
    }
    
    .error-box {
        background: #f8d7da;
        border: 1px solid #f5c6cb;
        border-radius: 5px;
        padding: 1rem;
        margin: 1rem 0;
        color: #721c24;
    }
    
    .info-box {
        background: #d1ecf1;
        border: 1px solid #bee5eb;
        border-radius: 5px;
        padding: 1rem;
        margin: 1rem 0;
        color: #0c5460;
    }
    
    .section-header {
        color: #1f77b4;
        font-size: 1.5rem;
        font-weight: bold;
        margin: 1.5rem 0 1rem 0;
        border-bottom: 2px solid #e0e0e0;
        padding-bottom: 0.5rem;
    }
    
    .download-button {
        background: linear-gradient(45deg, #28a745, #20c997);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 0.5rem 1rem;
        font-weight: bold;
        margin: 0.5rem 0;
    }
    
    .email-section {
        background: #f8f9fa;
        border-radius: 10px;
        padding: 1.5rem;
        margin: 1rem 0;
        border-left: 4px solid #667eea;
    }
</style>
""", unsafe_allow_html=True)

class AzureDevOpsAPI:
    def __init__(self, project_name=None, work_item_types=None, iteration_path=None):
        self.pat = os.getenv('AZURE_DEVOPS_PAT')
        self.organization = "Inatech"
        self.project = project_name or "Shiptech"
        self.work_item_types = work_item_types or ['Requirement', 'Change Request']
        self.iteration_path = iteration_path or "Shiptech\\12.10.0\\Roadmap"
        self.base_url = f"https://dev.azure.com/{self.organization}"
        
    def get_auth_headers(self):
        credentials = f":{self.pat}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        return {
            "Authorization": f"Basic {encoded_credentials}",
            "Content-Type": "application/json"
        }
    
    def make_request(self, url, headers=None):
        """Make a GET request with SSL verification disabled for corporate environments"""
        if headers is None:
            headers = self.get_auth_headers()
        
        try:
            # First try with SSL verification enabled
            response = requests.get(url, headers=headers, timeout=30)
            return response
        except requests.exceptions.SSLError:
            # If SSL fails, try with verification disabled (silently)
            response = requests.get(url, headers=headers, verify=False, timeout=30)
            return response
        except requests.exceptions.RequestException as e:
            st.error(f"❌ Request failed: {str(e)}")
            raise
    
    def make_post_request(self, url, headers=None, json_data=None):
        """Make a POST request with SSL verification disabled for corporate environments"""
        if headers is None:
            headers = self.get_auth_headers()
        
        try:
            # First try with SSL verification enabled
            response = requests.post(url, headers=headers, json=json_data, timeout=30)
            return response
        except requests.exceptions.SSLError:
            # If SSL fails, try with verification disabled (silently)
            response = requests.post(url, headers=headers, json=json_data, verify=False, timeout=30)
            return response
        except requests.exceptions.RequestException as e:
            st.error(f"❌ Request failed: {str(e)}")
            raise
    
    def get_roadmap_work_items(self):
        """Get work items from specified project and iteration"""
        url = f"{self.base_url}/{self.project}/_apis/wit/wiql?api-version=7.0"
        
        # Build work item types string for query
        work_item_types_str = "', '".join(self.work_item_types)
        
        query = {
            "query": f"SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = '{self.project}' AND [System.IterationPath] UNDER '{self.iteration_path}' AND [System.WorkItemType] IN ('{work_item_types_str}')"
        }
        
        response = self.make_post_request(url, json_data=query)
        if response.status_code == 200:
            return response.json()
        else:
            st.error(f"Error getting work items: {response.status_code}")
            return None
    
    def get_work_item_details(self, work_item_ids):
        """Get detailed information for work items in batches of 200"""
        if not work_item_ids:
            return []
        all_details = []
        batch_size = 200
        for i in range(0, len(work_item_ids), batch_size):
            batch_ids = work_item_ids[i:i+batch_size]
            ids_str = ",".join(map(str, batch_ids))
            url = f"{self.base_url}/_apis/wit/workitems?ids={ids_str}&$expand=all&api-version=7.1"
            response = self.make_request(url)
            if response.status_code == 200:
                all_details.extend(response.json().get('value', []))
            else:
                st.error(f"Error fetching work item details: {response.status_code}")
                st.write(f"Response: {response.text}")
        return all_details
    
    def get_child_task_details(self, child_ids):
        """Get details for child tasks"""
        if not child_ids:
            return []
            
        url = f"{self.base_url}/_apis/wit/workitemsbatch?api-version=7.0"
        
        payload = {
            "ids": child_ids,
            "fields": [
                "System.Id",
                "System.Title", 
                "System.WorkItemType",
                "System.IterationPath",
                "Microsoft.VSTS.Scheduling.OriginalEstimate",
                "Microsoft.VSTS.Scheduling.RemainingWork",
                "Microsoft.VSTS.Scheduling.CompletedWork"
            ]
        }
        
        response = self.make_post_request(url, json_data=payload)
        if response.status_code == 200:
            return response.json().get('value', [])
        else:
            st.error(f"Error getting child task details: {response.status_code}")
            return []

class EmailSender:
    def __init__(self):
        self.smtp_server = os.getenv('SMTP_SERVER', 'smtp.office365.com')
        self.smtp_port = int(os.getenv('SMTP_PORT', '587'))
        self.email = os.getenv('EMAIL_ADDRESS')
        self.password = os.getenv('EMAIL_PASSWORD')
    
    def send_email(self, to_emails, subject, html_content):
        """Send email using SMTP"""
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.email
            msg['To'] = to_emails
            
            html_part = MIMEText(html_content, 'html')
            msg.attach(html_part)
            
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.email, self.password)
            server.send_message(msg)
            server.quit()
            
            return True
        except Exception as e:
            st.error(f"Error sending email: {str(e)}")
            return False

def process_work_items(work_items_data):
    """Process work items and extract child relationships"""
    parent_work_items = {}
    
    for item in work_items_data:
        parent_id = item['id']
        parent_title = item['fields'].get('System.Title', 'Unknown Title')
        parent_state = item['fields'].get('System.State', 'Unknown State')
        assigned_to = item['fields'].get('System.AssignedTo', {}).get('displayName', 'Unassigned')
        
        # Initialize parent work item if not exists
        if parent_id not in parent_work_items:
            parent_work_items[parent_id] = {
                'parentId': parent_id,
                'parentTitle': parent_title,
                'parentState': parent_state,
                'assignedTo': assigned_to,
                'childIds': []
            }
        
        # Get child relationships
        relations = item.get('relations', [])
        hierarchy_relations = [rel for rel in relations if rel['rel'] == 'System.LinkTypes.Hierarchy-Forward']
        
        if hierarchy_relations:
            for relation in hierarchy_relations:
                child_id = int(relation['url'].split('/')[-1])
                parent_work_items[parent_id]['childIds'].append(child_id)
        else:
            # Parent with no children - keep childIds as empty list
            pass
    
    return list(parent_work_items.values())

def create_summary_stats(df):
    """Create summary statistics"""
    total_items = len(df)
    total_estimate = df['OriginalEstimate'].sum()
    total_completed = df['CompletedWork'].sum()
    total_remaining = df['RemainingWork'].sum()
    
    return {
        'total_items': total_items,
        'total_estimate': total_estimate,
        'total_completed': total_completed,
        'total_remaining': total_remaining
    }

@st.cache_data
def cached_create_summary_stats(df):
    """Cached version of summary statistics"""
    return create_summary_stats(df)

def generate_excel_download(df, project_name="Shiptech"):
    """Generate Excel file for download"""
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name=f'{project_name} Report', index=False)
    
    output.seek(0)
    return output

def display_metrics(stats):
    """Display metrics in a clean card layout"""
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">{stats['total_items']}</div>
            <div class="metric-label">Total Work Items</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">{stats['total_estimate']:.1f}</div>
            <div class="metric-label">Total Estimate (hrs)</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">{stats['total_completed']:.1f}</div>
            <div class="metric-label">Completed Work (hrs)</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">{stats['total_remaining']:.1f}</div>
            <div class="metric-label">Remaining Work (hrs)</div>
        </div>
        """, unsafe_allow_html=True)
    
    # Add progress bar below the metrics
    progress_percentage = (stats['total_completed'] / stats['total_estimate']) * 100 if stats['total_estimate'] > 0 else 0
    
    st.markdown(f"""
    <div style="margin-top: 20px; padding: 20px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 10px; color: white;">
        <div style="display: flex; justify-content: space-between; margin-bottom: 10px; font-size: 16px; font-weight: 600;">
            <span>📈 Overall Progress: {progress_percentage:.1f}%</span>
            <span>{stats['total_completed']:.1f}h / {stats['total_estimate']:.1f}h</span>
        </div>
        <div style="width: 100%; height: 12px; background-color: rgba(255,255,255,0.3); border-radius: 6px; overflow: hidden;">
            <div style="height: 100%; background: linear-gradient(90deg, #28a745 0%, #20c997 100%); border-radius: 6px; width: {progress_percentage:.1f}%; transition: width 0.3s ease;"></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

def extract_sprint_names_from_child_tasks(child_tasks_data):
    """Extract unique sprint names from child work items"""
    sprint_names = set()
    for task in child_tasks_data:
        iteration_path = task['fields'].get('System.IterationPath', '')
        if iteration_path:
            # Extract sprint name from full iteration path
            sprint_name = iteration_path.split('\\')[-1] if '\\' in iteration_path else iteration_path
            if sprint_name and sprint_name not in ['Roadmap', '']:  # Filter out non-sprint paths
                sprint_names.add(sprint_name)
    return sorted(list(sprint_names))

def open_email_app_with_report(df, project_name, iteration_path, stats):
    """Create HTML email file for download and browser preview"""
    import tempfile
    import os
    
    # Create email subject
    current_date = datetime.now().strftime('%B %d, %Y')
    subject = f"📌 {project_name} Project Summary – {current_date}"
    
    # Create professional HTML email body
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{project_name} Project Summary</title>
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                line-height: 1.6;
                color: #333;
                max-width: 1000px;
                margin: 0 auto;
                padding: 20px;
                background-color: #f8f9fa;
            }}
            .email-container {{
                background-color: #ffffff;
                border-radius: 8px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                padding: 30px;
                margin: 20px 0;
            }}
            .header {{
                text-align: center;
                border-bottom: 3px solid #007bff;
                padding-bottom: 20px;
                margin-bottom: 30px;
            }}
            .header h1 {{
                color: #007bff;
                margin: 0;
                font-size: 28px;
                font-weight: 600;
            }}
            .header p {{
                color: #666;
                margin: 10px 0 0 0;
                font-size: 16px;
            }}
            .summary-section {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 25px;
                border-radius: 8px;
                margin: 25px 0;
            }}
            .summary-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 20px;
                margin-top: 20px;
            }}
            .summary-item {{
                text-align: center;
                padding: 15px;
                background: rgba(255,255,255,0.1);
                border-radius: 6px;
            }}
            .summary-value {{
                font-size: 24px;
                font-weight: bold;
                margin-bottom: 5px;
            }}
            .summary-label {{
                font-size: 14px;
                opacity: 0.9;
            }}
            .table-container {{
                margin: 30px 0;
                overflow-x: auto;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                background: white;
                border-radius: 8px;
                overflow: hidden;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                font-size: 13px;
            }}
            th {{
                background: linear-gradient(135deg, #007bff 0%, #0056b3 100%);
                color: white;
                padding: 12px 15px;
                text-align: left;
                font-weight: 600;
                font-size: 14px;
            }}
            td {{
                padding: 12px 15px;
                border-bottom: 1px solid #eee;
                font-size: 13px;
                vertical-align: top;
            }}
            tr:nth-child(even) {{
                background-color: #f8f9fa;
            }}
            tr:hover {{
                background-color: #e3f2fd;
            }}
            .status-badge {{
                padding: 4px 8px;
                border-radius: 12px;
                font-size: 11px;
                font-weight: 600;
                text-transform: uppercase;
                display: inline-block;
            }}
            .status-resolved {{
                background-color: #d4edda;
                color: #155724;
            }}
            .status-active {{
                background-color: #fff3cd;
                color: #856404;
            }}
            .status-planned {{
                background-color: #d1ecf1;
                color: #0c5460;
            }}
            .status-code-review {{
                background-color: #f8d7da;
                color: #721c24;
            }}
            .footer {{
                text-align: center;
                margin-top: 30px;
                padding-top: 20px;
                border-top: 1px solid #eee;
                color: #666;
                font-size: 14px;
            }}
            .progress-bar {{
                width: 100%;
                height: 8px;
                background-color: #e9ecef;
                border-radius: 4px;
                overflow: hidden;
                margin-top: 5px;
            }}
            .progress-fill {{
                height: 100%;
                background: linear-gradient(90deg, #28a745 0%, #20c997 100%);
                border-radius: 4px;
                transition: width 0.3s ease;
            }}
            .instructions {{
                background: #fff3cd;
                border: 1px solid #ffeaa7;
                border-radius: 8px;
                padding: 15px;
                margin: 20px 0;
                color: #856404;
            }}
        </style>
    </head>
    <body>
        <div class="email-container">
            <div class="header">
                <h1>📊 {project_name} Project Summary</h1>
                <p>Progress Report • {current_date}</p>
                <p>Iteration Path: {iteration_path}</p>
            </div>
            
            <div class="summary-section">
                <h2 style="margin: 0 0 20px 0; color: white;">📈 Project Overview</h2>
                <div class="summary-grid">
                    <div class="summary-item">
                        <div class="summary-value">{stats['total_items']}</div>
                        <div class="summary-label">Total Work Items</div>
                    </div>
                    <div class="summary-item">
                        <div class="summary-value">{stats['total_estimate']:.1f}h</div>
                        <div class="summary-label">Original Estimate</div>
                    </div>
                    <div class="summary-item">
                        <div class="summary-value">{stats['total_completed']:.1f}h</div>
                        <div class="summary-label">Completed Work</div>
                    </div>
                    <div class="summary-item">
                        <div class="summary-value">{stats['total_remaining']:.1f}h</div>
                        <div class="summary-label">Remaining Work</div>
                    </div>
                </div>
                <div style="margin-top: 20px;">
                    <div style="display: flex; justify-content: space-between; color: white; font-size: 14px;">
                        <span>Progress: {((stats['total_completed'] / stats['total_estimate']) * 100):.1f}%</span>
                        <span>{stats['total_completed']:.1f}h / {stats['total_estimate']:.1f}h</span>
                    </div>
                    <div class="progress-bar">
                        <div class="progress-fill" style="width: {((stats['total_completed'] / stats['total_estimate']) * 100):.1f}%;"></div>
                    </div>
                </div>
            </div>
            
            <div class="table-container">
                <h2 style="color: #333; margin-bottom: 20px;">📋 Work Items Details</h2>
                <table>
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Title</th>
                            <th>State</th>
                            <th>Assigned To</th>
                            <th>Original Estimate</th>
                            <th>Completed</th>
                            <th>Remaining</th>
                            <th>Progress</th>
                        </tr>
                    </thead>
                    <tbody>
    """
    
    # Add work items data
    for _, row in df.iterrows():
        # Calculate progress percentage
        total_estimate = row['OriginalEstimate']
        completed = row['CompletedWork']
        progress_pct = (completed / total_estimate * 100) if total_estimate > 0 else 0
        
        # Determine status badge class
        state_lower = row['State'].lower()
        if 'resolved' in state_lower:
            status_class = 'status-resolved'
        elif 'active' in state_lower:
            status_class = 'status-active'
        elif 'planned' in state_lower:
            status_class = 'status-planned'
        elif 'code review' in state_lower:
            status_class = 'status-code-review'
        else:
            status_class = 'status-planned'
        
        html_content += f"""
                        <tr>
                            <td><strong>{row['ID']}</strong></td>
                            <td>{row['Title']}</td>
                            <td><span class="status-badge {status_class}">{row['State']}</span></td>
                            <td>{row['AssignedTo']}</td>
                            <td>{row['OriginalEstimate']:.1f}h</td>
                            <td>{row['CompletedWork']:.1f}h</td>
                            <td>{row['RemainingWork']:.1f}h</td>
                            <td>
                                <div style="display: flex; align-items: center; gap: 8px;">
                                    <span style="font-size: 12px; color: #666;">{progress_pct:.0f}%</span>
                                    <div class="progress-bar" style="width: 60px;">
                                        <div class="progress-fill" style="width: {progress_pct:.1f}%;"></div>
                                    </div>
                                </div>
                            </td>
                        </tr>
        """
    
    html_content += """
                    </tbody>
                </table>
            </div>
            
            <div class="footer">
                <p>📧 This report was generated automatically by the Project Report Generator</p>
                <p>📅 Generated on {current_date} • {project_name} Project</p>
            </div>
        </div>
    </body>
    </html>
    """.format(current_date=current_date, project_name=project_name)
    
    # Store HTML content in session state for download
    st.session_state.html_email_content = html_content
    st.session_state.html_email_filename = f"{project_name.lower()}_project_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    
    # Open HTML file in browser for preview
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
        f.write(html_content)
        temp_file = f.name
    
    try:
        import webbrowser
        webbrowser.open(f'file://{temp_file}')
        return True
    except Exception as e:
        st.error(f"Error opening HTML preview: {str(e)}")
        return False

def make_work_item_link(id, org, base_url, project):
    url = f"{base_url}{org}/{project}/_workitems/edit/{id}"
    return f'<a href="{url}" target="_blank">{id}</a>'

def main():
    # Initialize session state
    if 'display_report' not in st.session_state:
        st.session_state.display_report = True
    if 'send_email' not in st.session_state:
        st.session_state.send_email = False
    if 'email_addresses' not in st.session_state:
        st.session_state.email_addresses = "anitha.k@inatech.com, jayaramki.chandrasekaran@inatech.com"
    if 'report_data' not in st.session_state:
        st.session_state.report_data = None
    if 'report_generated' not in st.session_state:
        st.session_state.report_generated = False
    
    # Initialize project selection in session state
    if 'selected_project' not in st.session_state:
        st.session_state.selected_project = Project.SHIPTECH.value
    if 'selected_work_item_types' not in st.session_state:
        st.session_state.selected_work_item_types = [WorkItemType.REQUIREMENT.value, WorkItemType.CHANGE_REQUEST.value]
    if 'selected_iteration_path' not in st.session_state:
        st.session_state.selected_iteration_path = IterationPath.ROADMAP.value
    if 'selected_child_iteration_path' not in st.session_state:
        st.session_state.selected_child_iteration_path = "All Sprints"
    if 'available_sprints' not in st.session_state:
        st.session_state.available_sprints = ["All Sprints"]
    if 'sprint_filter_ready' not in st.session_state:
        st.session_state.sprint_filter_ready = False
    if 'force_sprint_refresh' not in st.session_state:
        st.session_state.force_sprint_refresh = False
    
    # Header
    st.markdown('<h1 class="main-header">📊 Project Report Generator</h1>', unsafe_allow_html=True)
    
    # Initialize API and Email classes (before sidebar to avoid UnboundLocalError)
    api = AzureDevOpsAPI(
        project_name=st.session_state.selected_project,
        work_item_types=st.session_state.selected_work_item_types,
        iteration_path=st.session_state.selected_iteration_path
    )
    email_sender = EmailSender()
    
    # Check if we need to update sprint filter after report generation
    if st.session_state.report_generated and 'available_sprints' in st.session_state:
        available_sprints = st.session_state.get('available_sprints', ["All Sprints"])
        has_sprints = len(available_sprints) > 1
        if has_sprints:
            st.session_state.sprint_filter_ready = True
    
    # Configuration section in main content
    st.markdown('<div class="section-header">⚙️ Configuration</div>', unsafe_allow_html=True)
    
    # Check if Azure DevOps PAT is configured
    if not api.pat:
        st.error("⚠️ Azure DevOps PAT not configured")
        st.info("Please set AZURE_DEVOPS_PAT in your environment variables")
        return
    
    # Project Settings
    st.subheader("📋 Project Settings")
    
    # Create columns for better layout
    col1, col2, col3 = st.columns(3)
    
    with col1:
        # Project dropdown
        project_options = [project.value for project in Project]
        selected_project = st.selectbox(
            "Select Project",
            options=project_options,
            index=project_options.index(st.session_state.selected_project),
            key="project_selector"
        )
    
    with col2:
        # Work Item Types selection
        work_item_type_options = [wit.value for wit in WorkItemType]
        selected_work_item_types = st.multiselect(
            "Select Work Item Types",
            options=work_item_type_options,
            default=st.session_state.selected_work_item_types,
            key="work_item_types_selector"
        )
    
    with col3:
        # Iteration Path selection
        iteration_options = [iter_path.value for iter_path in IterationPath]
        selected_iteration_path = st.selectbox(
            "Select Iteration Path",
            options=iteration_options,
            index=iteration_options.index(st.session_state.selected_iteration_path),
            key="iteration_path_selector"
        )
    
    # Child Iteration Path (Sprint) selection
    available_sprints = st.session_state.get('available_sprints', ["All Sprints"])
    has_sprints = len(available_sprints) > 1  # More than just "All Sprints"
    
    if has_sprints and st.session_state.report_generated:
        child_iteration_options = available_sprints
        selected_child_iteration_path = st.selectbox(
            "Select Child Sprint",
            options=child_iteration_options,
            index=child_iteration_options.index(st.session_state.selected_child_iteration_path) if st.session_state.selected_child_iteration_path in child_iteration_options else 0,
            key="child_iteration_path_selector"
        )
    else:
        # Hide the sprint filter until we have child data
        selected_child_iteration_path = "All Sprints"
        if not st.session_state.report_generated:
            st.info("🏃 **Child Sprint Filter:** Will be available after generating report")
        else:
            st.info("🏃 **Child Sprint Filter:** No sprints found in child work items")
    
    # Update session state
    st.session_state.selected_project = selected_project
    st.session_state.selected_work_item_types = selected_work_item_types
    st.session_state.selected_iteration_path = selected_iteration_path
    st.session_state.selected_child_iteration_path = selected_child_iteration_path
    

    
    # Main content area
    st.markdown('<div class="section-header">🚀 Generate Report</div>', unsafe_allow_html=True)
    
    # Generate report button
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        generate_button = st.button("🚀 Generate Project Report", use_container_width=True)
    
    # Store report data in session state if generated
    if generate_button or st.session_state.report_generated:
        if generate_button:
            st.session_state.report_generated = True
            st.session_state.report_data = None  # Reset data for new generation
        with st.spinner("🔄 Fetching data from Azure DevOps..."):
            try:
                # Step 1: Get roadmap work items
                with st.status("📋 Fetching work items...", expanded=True) as status:
                    roadmap_data = api.get_roadmap_work_items()
                    if not roadmap_data:
                        st.error("❌ Failed to fetch work items")
                        return
                    
                    work_item_ids = [item['id'] for item in roadmap_data.get('workItems', [])]
                    
                    # Add detailed logging
                    st.write(f"📊 **Found {len(work_item_ids)} work items**")
                    st.write(f"🔍 **Project:** {st.session_state.selected_project}")
                    st.write(f"📋 **Work Item Types:** {st.session_state.selected_work_item_types}")
                    st.write(f"🛤️ **Iteration Path:** {st.session_state.selected_iteration_path}")
                    st.write(f"🔍 **Work Item IDs:** {work_item_ids}")
                    
                    # Show work item types if available
                    work_item_types = []
                    for item in roadmap_data.get('workItems', []):
                        if 'fields' in item and 'System.WorkItemType' in item['fields']:
                            work_item_types.append(item['fields']['System.WorkItemType'])
                    
                    if work_item_types:
                        st.write(f"📋 **Work Item Types:** {list(set(work_item_types))}")
                    
                    status.update(label=f"✅ Found {len(work_item_ids)} work items", state="complete")
                
                # Step 2: Get detailed work item information
                with st.status("🔍 Getting work item details...", expanded=True) as status:
                    work_items_data = api.get_work_item_details(work_item_ids)
                    
                    # Add detailed logging
                    st.write(f"📊 **Retrieved details for {len(work_items_data)} work items**")
                    
                    # Show parent work item details
                    parent_details = []
                    for item in work_items_data:
                        title = item['fields'].get('System.Title', 'Unknown Title')
                        state = item['fields'].get('System.State', 'Unknown State')
                        assigned_to = item['fields'].get('System.AssignedTo', {}).get('displayName', 'Unassigned')
                        parent_details.append(f"ID {item['id']}: {title} ({state}) - {assigned_to}")
                    
                    st.write("📋 **Parent Work Items:**")
                    for detail in parent_details[:5]:  # Show first 5
                        st.write(f"  • {detail}")
                    if len(parent_details) > 5:
                        st.write(f"  • ... and {len(parent_details) - 5} more")
                    
                    status.update(label=f"✅ Retrieved details for {len(work_items_data)} work items", state="complete")
                
                # Step 3: Process work items and extract child relationships
                with st.status("🔗 Processing parent-child relationships...", expanded=True) as status:
                    parent_work_items = process_work_items(work_items_data)
                    
                    # Add detailed logging
                    st.write(f"📊 **Processed {len(parent_work_items)} parent work items**")
                    
                    # Show relationship details
                    total_children = sum(len(parent['childIds']) for parent in parent_work_items)
                    st.write(f"👥 **Total child relationships found:** {total_children}")
                    
                    # Show parent-child breakdown
                    st.write("🔗 **Parent-Child Breakdown:**")
                    for parent in parent_work_items[:5]:  # Show first 5
                        child_count = len(parent['childIds'])
                        st.write(f"  • {parent['parentTitle']}: {child_count} children")
                    if len(parent_work_items) > 5:
                        st.write(f"  • ... and {len(parent_work_items) - 5} more parents")
                    
                    status.update(label=f"✅ Processed {len(parent_work_items)} parent work items", state="complete")
                
                # Step 4: Get child task details
                with st.status("📊 Fetching child task details...", expanded=True) as status:
                    # Collect all child IDs from all parent work items
                    all_child_ids = []
                    for parent_item in parent_work_items:
                        all_child_ids.extend(parent_item['childIds'])
                    
                    child_tasks_data = api.get_child_task_details(all_child_ids)
                    
                    # Extract available sprints from child tasks
                    available_sprints = extract_sprint_names_from_child_tasks(child_tasks_data)
                    st.session_state.available_sprints = ["All Sprints"] + available_sprints
                    
                    # Add detailed logging
                    st.write(f"📊 **Retrieved {len(child_tasks_data)} child tasks**")
                    
                    # Show child task summary
                    if child_tasks_data:
                        total_estimate = sum(task['fields'].get('Microsoft.VSTS.Scheduling.OriginalEstimate', 0) or 0 for task in child_tasks_data)
                        total_completed = sum(task['fields'].get('Microsoft.VSTS.Scheduling.CompletedWork', 0) or 0 for task in child_tasks_data)
                        total_remaining = sum(task['fields'].get('Microsoft.VSTS.Scheduling.RemainingWork', 0) or 0 for task in child_tasks_data)
                        
                        st.write(f"⏱️ **Total Estimates:** {total_estimate:.1f} hrs")
                        st.write(f"✅ **Total Completed:** {total_completed:.1f} hrs")
                        st.write(f"⏳ **Total Remaining:** {total_remaining:.1f} hrs")
                        
                        # Show child iteration paths
                        child_iteration_paths = []
                        for task in child_tasks_data:
                            iteration_path = task['fields'].get('System.IterationPath', 'Unknown')
                            if iteration_path not in child_iteration_paths:
                                child_iteration_paths.append(iteration_path)
                        
                        st.write(f"🛤️ **Child Iteration Paths:** {child_iteration_paths}")
                        st.write(f"🏃 **Available Sprints:** {available_sprints}")
                        
                        # Force UI update by showing the sprint filter is ready
                        st.session_state.sprint_filter_ready = True
                        
                        # Force immediate UI refresh for sprint filter
                        st.session_state.force_sprint_refresh = True
                
                    # Show sample child tasks
                    st.write("📋 **Sample Child Tasks:**")
                    for task in child_tasks_data[:3]:  # Show first 3
                        title = task['fields'].get('System.Title', 'Unknown Title')
                        estimate = task['fields'].get('Microsoft.VSTS.Scheduling.OriginalEstimate', 0) or 0
                        completed = task['fields'].get('Microsoft.VSTS.Scheduling.CompletedWork', 0) or 0
                        iteration_path = task['fields'].get('System.IterationPath', 'Unknown')
                        st.write(f"  • {title}: {estimate} hrs (completed: {completed} hrs) - {iteration_path}")
                    if len(child_tasks_data) > 3:
                        st.write(f"  • ... and {len(child_tasks_data) - 3} more tasks")
                    
                    status.update(label=f"✅ Retrieved {len(child_tasks_data)} child tasks", state="complete")
                
                # Step 5: Create comprehensive dataset
                with st.status("📈 Compiling final report...", expanded=True) as status:
                    final_data = []
                    
                    for parent_item in parent_work_items:
                        parent_data = {
                            'ID': parent_item['parentId'],
                            'Title': parent_item['parentTitle'],
                            'State': parent_item['parentState'],
                            'AssignedTo': parent_item['assignedTo'],
                            'OriginalEstimate': 0,
                            'CompletedWork': 0,
                            'RemainingWork': 0
                        }
                        
                        # Sum up all child task data for this parent
                        child_count = 0
                        for child_task in child_tasks_data:
                            if child_task['id'] in parent_item['childIds']:
                                # Check if child iteration path matches the selected sprint
                                child_iteration_path = child_task['fields'].get('System.IterationPath', '')
                                selected_child_sprint = st.session_state.selected_child_iteration_path
                                
                                # Extract sprint name from full iteration path (e.g., "Sprint 1" from "Shiptech\12.10.0\Roadmap\Sprint 1")
                                child_sprint = child_iteration_path.split('\\')[-1] if '\\' in child_iteration_path else child_iteration_path
                                
                                # Include child if it matches selected sprint or if "All Sprints" is selected
                                if selected_child_sprint == "All Sprints" or child_sprint == selected_child_sprint:
                                    parent_data['OriginalEstimate'] += child_task['fields'].get('Microsoft.VSTS.Scheduling.OriginalEstimate', 0) or 0
                                    parent_data['CompletedWork'] += child_task['fields'].get('Microsoft.VSTS.Scheduling.CompletedWork', 0) or 0
                                    parent_data['RemainingWork'] += child_task['fields'].get('Microsoft.VSTS.Scheduling.RemainingWork', 0) or 0
                                    child_count += 1
                        
                        # Only include parent if it has children in the selected sprint (or if "All Sprints" is selected)
                        if child_count > 0 or st.session_state.selected_child_iteration_path == "All Sprints":
                            final_data.append(parent_data)
                    
                    # Create DataFrame and store in session state
                    df = pd.DataFrame(final_data)
                    st.session_state.report_data = df
                    
                    # Add detailed logging
                    st.write(f"📊 **Final Report Summary:**")
                    st.write(f"  • **Total Parent Items:** {len(final_data)}")
                    st.write(f"  • **Total Original Estimate:** {df['OriginalEstimate'].sum():.1f} hrs")
                    st.write(f"  • **Total Completed Work:** {df['CompletedWork'].sum():.1f} hrs")
                    st.write(f"  • **Total Remaining Work:** {df['RemainingWork'].sum():.1f} hrs")
                    st.write(f"  • **Child Sprint Filter:** {st.session_state.selected_child_iteration_path}")
                    
                    # Show sample aggregated data
                    st.write("📋 **Sample Aggregated Data:**")
                    for i, row in df.head(3).iterrows():
                        st.write(f"  • {row['Title']}: {row['OriginalEstimate']:.1f} hrs (completed: {row['CompletedWork']:.1f} hrs)")
                    
                    status.update(label="✅ Report compilation complete", state="complete")
                
                # Display results
                st.success("✅ Report generated successfully!")
                
                # Force sidebar update for sprint filter
                if st.session_state.force_sprint_refresh:
                    st.session_state.force_sprint_refresh = False
                
                # Display summary statistics
                st.markdown('<div class="section-header">📊 Summary Statistics</div>', unsafe_allow_html=True)
                stats = create_summary_stats(df)
                display_metrics(stats)
                
                # Display data table
                st.markdown('<div class="section-header">📋 Work Items Details</div>', unsafe_allow_html=True)
                
                # Create a container for filtering and display
                with st.container():
                    # Initialize filter states
                    if 'state_filter' not in st.session_state:
                        st.session_state.state_filter = 'All'
                    if 'assigned_filter' not in st.session_state:
                        st.session_state.assigned_filter = 'All'
                    
                    # Cache unique values to prevent recalculation
                    if 'unique_states' not in st.session_state or 'unique_assignees' not in st.session_state:
                        st.session_state.unique_states = ['All'] + sorted(df['State'].unique())
                        st.session_state.unique_assignees = ['All'] + sorted(df['AssignedTo'].unique())
                    
                    # Add filtering options with reactive updates
                    col1, col2 = st.columns(2)
                    with col1:
                        # Get unique states and create options
                        unique_states = st.session_state.unique_states
                        state_index = 0 if st.session_state.state_filter == 'All' else unique_states.index(st.session_state.state_filter) if st.session_state.state_filter in unique_states else 0
                        
                        state_filter = st.selectbox(
                            "Filter by State",
                            options=unique_states,
                            index=state_index,
                            key="state_filter"
                        )
                    
                    with col2:
                        # Get unique assignees and create options
                        unique_assignees = st.session_state.unique_assignees
                        assigned_index = 0 if st.session_state.assigned_filter == 'All' else unique_assignees.index(st.session_state.assigned_filter) if st.session_state.assigned_filter in unique_assignees else 0
                        
                        assigned_filter = st.selectbox(
                            "Filter by Assigned To",
                            options=unique_assignees,
                            index=assigned_index,
                            key="assigned_filter"
                        )
                    
                    # Apply filters efficiently using vectorized operations
                    filtered_df = df.copy()
                    if state_filter != 'All':
                        filtered_df = filtered_df[filtered_df['State'] == state_filter]
                    if assigned_filter != 'All':
                        filtered_df = filtered_df[filtered_df['AssignedTo'] == assigned_filter]
                    
                    # Store the filtered data for export
                    st.session_state.filtered_data = filtered_df
                    
                    # Display filtered data with optimized rendering and error handling
                    if not filtered_df.empty:
                        st.dataframe(
                            filtered_df,
                            use_container_width=True,
                            column_config={
                                "ID": st.column_config.NumberColumn("ID", help="Work Item ID"),
                                "Title": st.column_config.TextColumn("Title", help="Work Item Title"),
                                "State": st.column_config.TextColumn("State", help="Current State"),
                                "AssignedTo": st.column_config.TextColumn("Assigned To", help="Assigned Person"),
                                "OriginalEstimate": st.column_config.NumberColumn("Original Estimate (hrs)", help="Original time estimate"),
                                "CompletedWork": st.column_config.NumberColumn("Completed (hrs)", help="Completed work hours"),
                                "RemainingWork": st.column_config.NumberColumn("Remaining (hrs)", help="Remaining work hours")
                            },
                            hide_index=True
                        )
                    else:
                        st.info("📋 No work items match the selected filters. Try adjusting your filter criteria.")
                
                # Export options
                st.markdown('<div class="section-header">📥 Export Options</div>', unsafe_allow_html=True)
                
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    # Excel export
                    if 'filtered_data' in st.session_state:
                        excel_data = generate_excel_download(st.session_state.filtered_data, st.session_state.selected_project)
                        st.download_button(
                            label="📊 Download Excel Report",
                            data=excel_data.getvalue(),
                            file_name=f"{st.session_state.selected_project.lower()}_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True
                        )
                
                with col2:
                    # CSV export
                    if 'filtered_data' in st.session_state:
                        csv_data = st.session_state.filtered_data.to_csv(index=False)
                        st.download_button(
                            label="📄 Download CSV Report",
                            data=csv_data,
                            file_name=f"{st.session_state.selected_project.lower()}_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                            mime="text/csv",
                            use_container_width=True
                        )
                
                with col3:
                    # Email Report button
                    if 'filtered_data' in st.session_state:
                        def send_email_report_2():
                            if open_email_app_with_report(
                                st.session_state.filtered_data, 
                                st.session_state.selected_project, 
                                st.session_state.selected_iteration_path, 
                                stats
                            ):
                                st.success("✅ HTML preview opened! Download the file below.")
                            else:
                                st.error("❌ Failed to open HTML preview")
                        
                        st.button("📧 Email Report", use_container_width=True, on_click=send_email_report_2)
                        
                        # Download HTML file button
                        if 'html_email_content' in st.session_state:
                            st.download_button(
                                label="📄 Download HTML Email",
                                data=st.session_state.html_email_content,
                                file_name=st.session_state.html_email_filename,
                                mime="text/html",
                                use_container_width=True
                            )
                
            except Exception as e:
                st.error(f"❌ Error generating report: {str(e)}")
                st.exception(e)
    
    # Display existing report data if available
    elif st.session_state.report_data is not None:
        df = st.session_state.report_data
        
        # Ensure sprint filter is ready if we have report data
        if st.session_state.report_generated and 'available_sprints' in st.session_state:
            st.session_state.sprint_filter_ready = True
            # Force UI refresh by updating session state
            if len(st.session_state.available_sprints) > 1:
                st.session_state.sprint_filter_ready = True
                # Add a small trigger to force UI refresh
                st.session_state.force_sprint_refresh = True
        
        # Display summary statistics (cached)
        st.markdown('<div class="section-header">📊 Summary Statistics</div>', unsafe_allow_html=True)
        stats = cached_create_summary_stats(df)
        display_metrics(stats)
        
        # Display data table
        st.markdown('<div class="section-header">📋 Work Items Details</div>', unsafe_allow_html=True)
        
        # Create a container for filtering and display
        with st.container():
            # Initialize filter states
            if 'state_filter' not in st.session_state:
                st.session_state.state_filter = 'All'
            if 'assigned_filter' not in st.session_state:
                st.session_state.assigned_filter = 'All'
            
            # Cache unique values to prevent recalculation
            if 'unique_states' not in st.session_state or 'unique_assignees' not in st.session_state:
                st.session_state.unique_states = ['All'] + sorted(df['State'].unique())
                st.session_state.unique_assignees = ['All'] + sorted(df['AssignedTo'].unique())
            
            # Add filtering options with reactive updates
            col1, col2 = st.columns(2)
            with col1:
                # Get unique states and create options
                unique_states = st.session_state.unique_states
                state_index = 0 if st.session_state.state_filter == 'All' else unique_states.index(st.session_state.state_filter) if st.session_state.state_filter in unique_states else 0
                
                state_filter = st.selectbox(
                    "Filter by State",
                    options=unique_states,
                    index=state_index,
                    key="state_filter"
                )
            
            with col2:
                # Get unique assignees and create options
                unique_assignees = st.session_state.unique_assignees
                assigned_index = 0 if st.session_state.assigned_filter == 'All' else unique_assignees.index(st.session_state.assigned_filter) if st.session_state.assigned_filter in unique_assignees else 0
                
                assigned_filter = st.selectbox(
                    "Filter by Assigned To",
                    options=unique_assignees,
                    index=assigned_index,
                    key="assigned_filter"
                )
            
            # Apply filters efficiently using vectorized operations
            filtered_df = df.copy()
            if state_filter != 'All':
                filtered_df = filtered_df[filtered_df['State'] == state_filter]
            if assigned_filter != 'All':
                filtered_df = filtered_df[filtered_df['AssignedTo'] == assigned_filter]
            
            # Store the filtered data for export
            st.session_state.filtered_data = filtered_df
            
            # Display filtered data with optimized rendering and error handling
            if not filtered_df.empty:
                st.dataframe(
                    filtered_df,
                    use_container_width=True,
                    column_config={
                        "ID": st.column_config.NumberColumn("ID", help="Work Item ID"),
                        "Title": st.column_config.TextColumn("Title", help="Work Item Title"),
                        "State": st.column_config.TextColumn("State", help="Current State"),
                        "AssignedTo": st.column_config.TextColumn("Assigned To", help="Assigned Person"),
                        "OriginalEstimate": st.column_config.NumberColumn("Original Estimate (hrs)", help="Original time estimate"),
                        "CompletedWork": st.column_config.NumberColumn("Completed (hrs)", help="Completed work hours"),
                        "RemainingWork": st.column_config.NumberColumn("Remaining (hrs)", help="Remaining work hours")
                    },
                    hide_index=True
                )
            else:
                st.info("📋 No work items match the selected filters. Try adjusting your filter criteria.")
                
        # Export options
        st.markdown('<div class="section-header">📥 Export Options</div>', unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            # Excel export
            if 'filtered_data' in st.session_state:
                excel_data = generate_excel_download(st.session_state.filtered_data, st.session_state.selected_project)
                st.download_button(
                    label="📊 Download Excel Report",
                    data=excel_data.getvalue(),
                    file_name=f"{st.session_state.selected_project.lower()}_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
        
        with col2:
            # CSV export
            if 'filtered_data' in st.session_state:
                csv_data = st.session_state.filtered_data.to_csv(index=False)
                st.download_button(
                    label="📄 Download CSV Report",
                    data=csv_data,
                    file_name=f"{st.session_state.selected_project.lower()}_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv",
                    use_container_width=True
                )
        
        with col3:
            # Email Report button
            if 'filtered_data' in st.session_state:
                def send_email_report_2():
                    if open_email_app_with_report(
                        st.session_state.filtered_data, 
                        st.session_state.selected_project, 
                        st.session_state.selected_iteration_path, 
                        stats
                    ):
                        st.success("✅ HTML preview opened! Download the file below.")
                    else:
                        st.error("❌ Failed to open HTML preview")
                
                st.button("📧 Email Report", use_container_width=True, on_click=send_email_report_2)
                
                # Download HTML file button
                if 'html_email_content' in st.session_state:
                    st.download_button(
                        label="📄 Download HTML Email",
                        data=st.session_state.html_email_content,
                        file_name=st.session_state.html_email_filename,
                        mime="text/html",
                        use_container_width=True
                    )

if __name__ == "__main__":
    main() 