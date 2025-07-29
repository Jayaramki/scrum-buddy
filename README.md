# Scrum Buddy

A comprehensive Streamlit-based application for monitoring Azure DevOps projects, generating reports, and tracking sprint progress.

## 🏗️ Project Structure

This application consists of two main components:

### 📊 Project Report Generator (Main Application)
The primary application for generating comprehensive project reports from Azure DevOps data.

**Key Features:**
- **Multi-Project Support**: Configure different projects via enums (SHIPTECH, etc.)
- **Work Item Filtering**: Support for Requirements, Change Requests, Tasks, Bugs, and Features
- **Iteration Management**: Track work across different iteration paths and sprints
- **Report Generation**: Generate detailed project reports with work item analysis
- **Email Integration**: Send reports directly via email with SMTP configuration
- **Export Capabilities**: Download reports in various formats

### 🧠 Sprint Monitoring Dashboard
A dedicated page for real-time sprint monitoring and team performance tracking.

**Key Features:**
- **Tab-Based Interface**: Optimized navigation with lazy loading
  - **Sprint Metrics**: Overview of sprint progress and team summary
  - **Work Items Details**: Advanced data table with filtering and sorting
  - **Daily Progress Tracking**: Track work logged on specific dates
- **Smart API Management**: API calls only execute for active tabs
- **Automatic Cancellation**: Previous requests cancelled when switching tabs
- **Real-time Data**: Fresh data loading with manual refresh options
- **Advanced Visualizations**: Interactive charts and metrics using Plotly

## 🔧 Technical Implementation

### Architecture
- **Framework**: Streamlit with multi-page architecture
- **API Integration**: Azure DevOps REST API with authentication
- **Data Processing**: Pandas for data manipulation and analysis
- **Visualizations**: Plotly for interactive charts and graphs
- **Data Tables**: StreamLit AgGrid for advanced table functionality
- **Containerization**: Docker and Docker Compose support

### Advanced Features
- **CancellableRequest Class**: Thread-safe request cancellation mechanism
- **Session State Management**: Persistent state across page navigation
- **Data Caching**: Compressed data storage for performance optimization
- **Error Handling**: Comprehensive error handling and user feedback
- **Responsive Design**: Custom CSS for modern, professional styling

## 🚀 Installation & Setup

### Prerequisites
- Python 3.11+
- Azure DevOps Personal Access Token (PAT)
- SMTP server configuration (for email features - Upcoming feature)

### Local Development
```bash
# Clone the repository
git clone <repository-url>
cd Workfolw

# Install dependencies
pip install -r app/requirements.txt

# Set up environment variables (see Environment Variables section)
cp .env.example .env
# Edit .env with your configuration

# Run the application
streamlit run app/main.py
```

### Docker Deployment
```bash
# Using Docker Compose (recommended)
docker-compose up -d

# Or build and run manually
docker build -t azure-devops-monitor .
docker run -p 8501:8501 \
  -e AZURE_DEVOPS_PAT=your_pat \
  -e SMTP_SERVER=your_smtp_server \
  azure-devops-monitor
```

## ⚙️ Configuration

### Environment Variables

Create a `.env` file in the project root with the following variables:

```bash
# Azure DevOps Configuration
AZURE_DEVOPS_PAT=your_personal_access_token
ORGANIZATION=your_azure_devops_organization
AZURE_DEV_URL=https://dev.azure.com/your_organization

# Email Configuration (Optional)
SMTP_SERVER=your_smtp_server
SMTP_PORT=587
EMAIL_ADDRESS=your_email@domain.com
EMAIL_PASSWORD=your_email_password
```

### Project Configuration
Projects and work item types are configured via enums in `app/enums.py`:
- **Projects**: Configure available projects
- **Work Item Types**: Define supported work item types
- **Iteration Paths**: Set up iteration path options

## 📋 Usage

### Project Report Generator
1. **Select Configuration**: Choose project, work item types, and iteration path
2. **Generate Report**: Click generate to fetch data from Azure DevOps
3. **Review Results**: Analyze work items, progress metrics, and team performance
4. **Export/Email**: Download reports or send via email

### Sprint Monitoring Dashboard
1. **Navigate to Sprint Monitoring**: Use the sidebar to access the Sprint Monitoring page
2. **Select Context**: Choose project, team, and sprint
3. **Monitor Progress**: Switch between tabs to view different aspects of sprint progress
4. **Refresh Data**: Use refresh buttons to update data when needed

## 📊 Key Metrics & Analytics

- **Work Item Breakdown**: Tasks, Requirements, Change Requests, Bugs, Features
- **Progress Tracking**: Remaining vs. Completed work analysis
- **Team Performance**: Individual and team-level metrics
- **Sprint Velocity**: Historical and current sprint performance
- **Daily Progress**: Day-by-day work completion tracking

## 🛠️ Dependencies

- **streamlit>=1.47.0**: Web application framework
- **requests==2.31.0**: HTTP library for API calls
- **pandas==2.1.1**: Data manipulation and analysis
- **plotly**: Interactive visualizations
- **streamlit-aggrid==0.3.4**: Advanced data table component
- **python-dotenv==1.0.0**: Environment variable management
- **openpyxl==3.1.2**: Excel file support

## 🐳 Containerization

The application is fully containerized with:
- **Dockerfile**: Python 3.11-slim base with optimized dependencies
- **docker-compose.yml**: Complete deployment configuration
- **Environment Integration**: Secure environment variable handling
- **Port Configuration**: Streamlit server on port 8501

## 🔒 Security

- **Token Management**: Secure Azure DevOps PAT handling
- **Environment Variables**: Sensitive data stored in environment variables
- **SSL Verification**: Configurable SSL settings for enterprise environments
- **Error Logging**: Comprehensive logging without exposing sensitive information

## 📖 API Integration

The application integrates with Azure DevOps REST API v7.0 for:
- Work item queries and details
- Team and project information
- Iteration and sprint data
- Work item relationships and hierarchies
- Time tracking and progress data 
