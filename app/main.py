import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from requests.auth import HTTPBasicAuth
import plotly.express as px
import os
from dotenv import load_dotenv
from enums import WorkItemType, IterationPath
import threading
import time
from functools import wraps
import pickle
import gzip
import hashlib
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, DataReturnMode, JsCode
import urllib3
import bcrypt

# Suppress SSL warnings when verification is disabled
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Load environment variables
load_dotenv()

# Load secrets for Streamlit Cloud compatibility
def get_config_value(key, default=None):
    """Get configuration value from Streamlit secrets or environment variables"""
    try:
        # Try Streamlit secrets first (for Streamlit Cloud)
        if hasattr(st, 'secrets') and key in st.secrets:
            return st.secrets[key]
    except:
        pass
    
    # Fallback to environment variables (for local development)
    return os.getenv(key, default)

# Page configuration
st.set_page_config(
    page_title="Sprint Monitoring Dashboard",
    page_icon="🧠",
    layout="wide"
)

# No custom styling - using default Streamlit theme

# Azure DevOps Configuration
import base64

class ProgressiveLoader:
    """Progressive loader for better user experience during data loading"""
    def __init__(self, chunk_size=50):
        self.chunk_size = chunk_size
    
    def load_work_items_progressively(self, api_instance, work_item_ids, progress_callback=None, status_callback=None):
        """Load work items in small chunks with progress updates"""
        if not work_item_ids:
            return []
        
        all_details = []
        total_items = len(work_item_ids)
        
        if status_callback:
            status_callback(f"Starting to load {total_items} work items...")
        
        for i in range(0, total_items, self.chunk_size):
            chunk_ids = work_item_ids[i:i+self.chunk_size]
            
            # Update status
            if status_callback:
                status_callback(f"Loading chunk {i//self.chunk_size + 1}/{(total_items + self.chunk_size - 1)//self.chunk_size} ({len(chunk_ids)} items)...")
            
            # Load chunk
            chunk_details = api_instance.get_work_item_details(chunk_ids)
            all_details.extend(chunk_details)
            
            # Update progress
            progress = min((i + self.chunk_size) / total_items, 1.0)
            if progress_callback:
                progress_callback(progress)
            
            # Small delay to prevent overwhelming the API and show progress
            time.sleep(0.1)
        
        if status_callback:
            status_callback(f"✅ Successfully loaded {len(all_details)} work items")
        
        return all_details
    
    def load_work_item_history_progressively(self, api_instance, work_item_ids, start_date, end_date, progress_callback=None, status_callback=None):
        """Load work item history progressively with detailed progress"""
        if not work_item_ids:
            return []
        
        if status_callback:
            status_callback("🔄 Starting work item history analysis...")
        
        # First, get work item details in batches
        work_item_details = {}
        batch_size = 200
        total_batches = (len(work_item_ids) + batch_size - 1) // batch_size
        
        for i in range(0, len(work_item_ids), batch_size):
            try:
                batch_num = i // batch_size + 1
                if status_callback:
                    status_callback(f"📋 Loading work item details (batch {batch_num}/{total_batches})...")
                
                batch_ids = work_item_ids[i:i+batch_size]
                ids_string = ','.join(map(str, batch_ids))
                
                work_items_url = f"{api_instance.base_url}/_apis/wit/workItems?ids={ids_string}&$expand=all&api-version=7.1"
                response = api_instance.make_request(work_items_url)
                
                if response.status_code == 200:
                    work_items_data = response.json()
                    
                    for work_item in work_items_data.get('value', []):
                        work_item_id = work_item.get('id')
                        fields = work_item.get('fields', {})
                        work_item_details[work_item_id] = {
                            'title': fields.get('System.Title', 'Unknown Task'),
                            'state': fields.get('System.State', 'Unknown'),
                            'assigned_to': fields.get('System.AssignedTo', {}).get('displayName', 'Unassigned')
                        }
                
                # Update progress for details loading
                progress = min((i + batch_size) / len(work_item_ids), 1.0) * 0.3  # 30% of total progress
                if progress_callback:
                    progress_callback(progress)
                    
            except Exception as e:
                if status_callback:
                    status_callback(f"⚠️ Error in batch {batch_num}: {str(e)}")
                continue
        
        if status_callback:
            status_callback(f"📊 Analyzing history for {len(work_item_details)} work items...")
        
        # Now get the actual work item history for each work item
        task_updates = []
        total_work_items = len(work_item_details)
        
        # Reset progress to 0 before starting history processing to show actual progress from 0%
        if progress_callback:
            progress_callback(0.0)
        
        for idx, (work_item_id, work_item_info) in enumerate(work_item_details.items()):
            try:
                if status_callback:  # Update status for every item
                    status_callback(f"📅 Processing history for work item {idx + 1}/{total_work_items}...")
                
                # Get work item history
                history_url = f"{api_instance.base_url}/_apis/wit/workItems/{work_item_id}/updates?api-version=7.1"
                response = api_instance.make_request(history_url)

                if response.status_code == 200:
                    history_data = response.json()
                    
                    # Track completed work progression
                    completed_work_history = []
                    
                    for update in history_data.get('value', []):
                        fields = update.get('fields', {})
                        state_change_field = fields.get('System.ChangedDate', {})
                        update_date = state_change_field.get('newValue', '') if state_change_field else update.get('revisedDate', '')
                        if update_date:
                            update_datetime = datetime.fromisoformat(update_date.replace('Z', '+00:00'))
                            update_date_only = update_datetime.date()
                            
                            fields = update.get('fields', {})
                            completed_work_field = fields.get('Microsoft.VSTS.Scheduling.CompletedWork', {})
                            
                            if completed_work_field:
                                old_value = completed_work_field.get('oldValue', 0) or 0
                                new_value = completed_work_field.get('newValue', 0) or 0
                                
                                if new_value != old_value:  # Only track actual changes
                                    completed_work_history.append({
                                        'date': update_date_only,
                                        'datetime': update_datetime,  # Keep full datetime for sorting
                                        'old_value': old_value,
                                        'new_value': new_value,
                                        'revised_by': update.get('revisedBy', {}).get('displayName', 'Unknown'),
                                        'update_time': update_datetime.strftime('%H:%M')
                                    })
                    
                    # Sort history by datetime to ensure chronological order
                    completed_work_history.sort(key=lambda x: x['datetime'])
                    
                    # Process all dates in the sprint period
                    for current_date in [start_date + timedelta(days=x) for x in range((end_date - start_date).days + 1)]:
                        # Find all revisions with completed_work changes for this specific date
                        day_revisions = [item for item in completed_work_history if item['date'] == current_date]
                        
                        # If no revisions with completed_work changes for this day, skip it
                        if not day_revisions:
                            continue
                        
                        # Get the first and last revisions for this day
                        first_revision = day_revisions[0]  # First revision of the day
                        last_revision = day_revisions[-1]  # Last revision of the day
                        
                        # Determine previous_completed from first revision
                        if first_revision['old_value'] is not None and first_revision['old_value'] > 0:
                            # First revision has old_value, so this is yesterday's final value
                            previous_completed = first_revision['old_value']
                        else:
                            # First revision has no old_value, so this is the first entry for this task
                            previous_completed = 0
                        
                        # Get final value from last revision
                        target_completed = last_revision['new_value']
                        target_update_time = last_revision['update_time']
                        
                        # If last revision's new_value is 0, skip this day
                        if target_completed == 0:
                            continue
                        
                        # Calculate hours logged on the current date
                        hours_logged_on_date = target_completed - previous_completed
                        
                        # Only add if hours were actually logged on this date
                        if hours_logged_on_date > 0:
                            task_updates.append({
                                'Task_ID': work_item_id,
                                'Task_Title': work_item_info['title'],
                                'Team_Member': work_item_info['assigned_to'],
                                'Date': current_date,
                                'Hours_Updated': hours_logged_on_date,
                                'Old_Completed': previous_completed,
                                'New_Completed': target_completed,
                                'Update_Time': target_update_time,
                                'Task_State': work_item_info['state']
                            })
                
                # Update progress for history processing (now 0% to 100% for better UX)
                # Show actual progress from 0% to 100% during history processing
                progress = (idx + 1) / total_work_items
                if progress_callback:
                    progress_callback(progress)
                
                # Small delay to prevent overwhelming the API
                time.sleep(0.05)
                
            except Exception as e:
                if status_callback:
                    status_callback(f"⚠️ Error processing work item {work_item_id}: {str(e)}")
                continue
        
        if status_callback:
            status_callback(f"✅ Completed! Found {len(task_updates)} work updates")
        
        # Debug: Show which work items were processed
        if task_updates:
            debug_info = f"📊 Debug: Processed {len(work_item_details)} work items, found {len(task_updates)} updates"
            if status_callback:
                status_callback(debug_info)
        
        return task_updates

class DataCache:
    """Data cache with compression for efficient memory usage"""
    def __init__(self, max_cache_size_mb=50):
        self.max_cache_size = max_cache_size_mb * 1024 * 1024  # Convert to bytes
        self.cache = {}
        self.cache_metadata = {}
    
    def _generate_cache_key(self, data_type, params):
        """Generate unique cache key"""
        param_str = str(sorted(params.items()))
        return hashlib.md5(f"{data_type}:{param_str}".encode()).hexdigest()
    
    def _compress_data(self, data):
        """Compress data using gzip"""
        try:
            serialized = pickle.dumps(data)
            compressed = gzip.compress(serialized)
            return compressed
        except Exception as e:
            st.warning(f"Compression failed: {str(e)}")
            return None
    
    def _decompress_data(self, compressed_data):
        """Decompress data using gzip"""
        try:
            serialized = gzip.decompress(compressed_data)
            return pickle.loads(serialized)
        except Exception as e:
            st.warning(f"Decompression failed: {str(e)}")
            return None
    
    def _get_cache_size(self):
        """Calculate total cache size"""
        total_size = 0
        for key, data in self.cache.items():
            total_size += len(data)
        return total_size
    
    def _cleanup_cache(self):
        """Remove old entries if cache is too large"""
        if self._get_cache_size() > self.max_cache_size:
            # Remove oldest entries
            sorted_entries = sorted(
                self.cache_metadata.items(), 
                key=lambda x: x[1]['timestamp']
            )
            
            for key, _ in sorted_entries:
                if self._get_cache_size() <= self.max_cache_size * 0.8:  # Keep 80%
                    break
                del self.cache[key]
                del self.cache_metadata[key]
    
    def get(self, data_type, params, max_age_hours=24):
        """Get data from cache if available and not expired"""
        cache_key = self._generate_cache_key(data_type, params)
        
        if cache_key in self.cache:
            metadata = self.cache_metadata.get(cache_key, {})
            timestamp = metadata.get('timestamp', datetime.min)
            
            # Check if cache is still valid
            if datetime.now() - timestamp < timedelta(hours=max_age_hours):
                try:
                    compressed_data = self.cache[cache_key]
                    data = self._decompress_data(compressed_data)
                    if data is not None:
                        return data
                except Exception as e:
                    st.warning(f"Cache decompression failed: {str(e)}")
                    # Remove corrupted cache entry
                    del self.cache[cache_key]
                    del self.cache_metadata[cache_key]
        
        return None
    
    def set(self, data_type, params, data):
        """Store data in cache with compression"""
        cache_key = self._generate_cache_key(data_type, params)
        
        try:
            compressed_data = self._compress_data(data)
            if compressed_data is None:
                return False
            
            # Check if adding this would exceed cache size
            if self._get_cache_size() + len(compressed_data) > self.max_cache_size:
                self._cleanup_cache()
            
            self.cache[cache_key] = compressed_data
            self.cache_metadata[cache_key] = {
                'timestamp': datetime.now(),
                'data_type': data_type,
                'size_bytes': len(compressed_data),
                'original_size': len(pickle.dumps(data)) if data is not None else 0
            }
            
            return True
            
        except Exception as e:
            st.warning(f"Cache storage failed: {str(e)}")
            return False
    
    def get_cache_stats(self):
        """Get cache statistics"""
        total_compressed = self._get_cache_size()
        total_original = sum(meta.get('original_size', 0) for meta in self.cache_metadata.values())
        compression_ratio = (1 - total_compressed / total_original) * 100 if total_original > 0 else 0
        
        return {
            'total_entries': len(self.cache),
            'compressed_size_mb': total_compressed / (1024 * 1024),
            'original_size_mb': total_original / (1024 * 1024),
            'compression_ratio': compression_ratio,
            'cache_utilization': (total_compressed / self.max_cache_size) * 100
        }

class RateLimiter:
    """Rate limiter to prevent API throttling"""
    def __init__(self, max_requests_per_second=8):
        self.max_requests = max_requests_per_second
        self.request_times = []
        self.lock = threading.Lock()
    
    def wait_if_needed(self):
        """Wait if we're making requests too fast"""
        with self.lock:
            current_time = time.time()
            # Remove old requests (older than 1 second)
            self.request_times = [t for t in self.request_times if current_time - t < 1.0]
            
            if len(self.request_times) >= self.max_requests:
                # Wait until we can make another request
                sleep_time = 1.0 - (current_time - self.request_times[0])
                if sleep_time > 0:
                    time.sleep(sleep_time)
                    current_time = time.time()  # Update time after sleep
            
            self.request_times.append(current_time)

def rate_limited(max_requests_per_second=8):
    """Decorator to rate limit API calls"""
    limiter = RateLimiter(max_requests_per_second)
    
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            limiter.wait_if_needed()
            return func(*args, **kwargs)
        return wrapper
    return decorator

class CancellableRequest:
    """Wrapper for requests that can be cancelled"""
    def __init__(self):
        self.cancelled = False
        self._lock = threading.Lock()
    
    def cancel(self):
        with self._lock:
            self.cancelled = True
    
    def is_cancelled(self):
        with self._lock:
            return self.cancelled

class SprintMonitoringAPI:
    def __init__(self, project_name=None):
        self.pat = get_config_value('AZURE_DEVOPS_PAT')
        self.organization = get_config_value('AZURE_DEVOPS_ORG', 'Inatech')
        self.project = project_name or "Shiptech"
        self.base_url = f"https://dev.azure.com/{self.organization}"
        self.cancellable_request = CancellableRequest()
        self.rate_limiter = RateLimiter(max_requests_per_second=8)  # Azure DevOps limit
        
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
    
    def check_cancellation(self):
        """Check if the current request should be cancelled"""
        if self.cancellable_request.is_cancelled():
            raise Exception("Request was cancelled")
    
    @rate_limited(8)
    def get_projects(self):
        """Get all projects in the organization"""
        # Try to get from cache first
        cache_params = {'organization': self.organization}
        cached_data = st.session_state.data_cache.get('projects', cache_params)
        if cached_data is not None:
            return cached_data
        
        # If not in cache, fetch from API
        url = f"{self.base_url}/_apis/projects?api-version=7.1"
        response = self.make_request(url)
        if response.status_code == 200:
            projects_data = response.json()
            projects = projects_data.get('value', [])
            
            # Store in cache
            st.session_state.data_cache.set('projects', cache_params, projects)
            return projects
        else:
            st.error(f"Error getting projects: {response.status_code}")
            return []
    
    @rate_limited(8)
    def get_teams(self):
        """Get all teams in the project"""
        # Try to get from cache first
        cache_params = {'organization': self.organization, 'project': self.project}
        cached_data = st.session_state.data_cache.get('teams', cache_params)
        if cached_data is not None:
            return cached_data
        
        # If not in cache, fetch from API
        url = f"{self.base_url}/_apis/teams?api-version=7.1-preview.3"
        response = self.make_request(url)
        if response.status_code == 200:
            teams_data = response.json()
            # Filter teams for the current project
            project_teams = [team for team in teams_data.get('value', []) if team.get('projectName') == self.project]
            
            # Store in cache
            st.session_state.data_cache.set('teams', cache_params, project_teams)
            return project_teams
        else:
            st.error(f"Error getting teams: {response.status_code}")
            return []
    
    @rate_limited(8)
    def get_iterations_for_team(self, team_name):
        """Get iterations for a specific team"""
        # Try to get from cache first
        cache_params = {'organization': self.organization, 'project': self.project, 'team': team_name}
        cached_data = st.session_state.data_cache.get('iterations', cache_params)
        if cached_data is not None:
            return cached_data
        
        # If not in cache, fetch from API
        url = f"{self.base_url}/{self.project}/{team_name}/_apis/work/teamsettings/iterations?api-version=7.0"
        response = self.make_request(url)
        if response.status_code == 200:
            iterations = response.json().get('value', [])
            
            # Store in cache
            st.session_state.data_cache.set('iterations', cache_params, iterations)
            return iterations
        else:
            st.error(f"Error getting iterations for team {team_name}: {response.status_code}")
            return []
    
    @rate_limited(8)
    def get_work_items(self, iteration_path):
        """Get work items for a specific iteration path"""
        # Try to get from cache first
        cache_params = {'organization': self.organization, 'project': self.project, 'iteration_path': iteration_path}
        cached_data = st.session_state.data_cache.get('work_item_ids', cache_params)
        if cached_data is not None:
            # Only show cache message once per session to avoid spam
            if 'work_item_ids_cache_shown' not in st.session_state:
                st.success("⚡ Fast loading from cache")
                st.session_state.work_item_ids_cache_shown = True
            return cached_data
        
        # If not in cache, fetch from API
        url = f"{self.base_url}/{self.project}/_apis/wit/wiql?api-version=7.0"
        query = {
            "query": f"SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = '{self.project}' AND [System.IterationPath] = '{iteration_path}' AND [System.WorkItemType] = 'Task'"
        }
        response = self.make_post_request(url, json_data=query)
        if response.status_code == 200:
            work_items = response.json().get('workItems', [])
            work_item_ids = [item['id'] for item in work_items]
            
            # Store in cache
            st.session_state.data_cache.set('work_item_ids', cache_params, work_item_ids)
            return work_item_ids
        else:
            st.error(f"Error getting work items: {response.status_code}")
            return []
    
    @rate_limited(8)
    def get_all_work_items(self, iteration_path):
        """Get all work items (not just tasks) for a specific iteration path"""
        # Try to get from cache first
        cache_params = {'organization': self.organization, 'project': self.project, 'iteration_path': iteration_path, 'all_types': True}
        cached_data = st.session_state.data_cache.get('all_work_item_ids', cache_params)
        if cached_data is not None:
            # Only show cache message once per session to avoid spam
            if 'all_work_item_ids_cache_shown' not in st.session_state:
                st.success("⚡ Fast loading from cache")
                st.session_state.all_work_item_ids_cache_shown = True
            return cached_data
        
        # If not in cache, fetch from API
        url = f"{self.base_url}/{self.project}/_apis/wit/wiql?api-version=7.0"
        query = {
            "query": f"SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = '{self.project}' AND [System.IterationPath] = '{iteration_path}'"
        }
        response = self.make_post_request(url, json_data=query)
        if response.status_code == 200:
            work_items = response.json().get('workItems', [])
            work_item_ids = [item['id'] for item in work_items]
            
            # Store in cache
            st.session_state.data_cache.set('all_work_item_ids', cache_params, work_item_ids)
            return work_item_ids
        else:
            st.error(f"Error getting all work items: {response.status_code}")
            return []
    
    def get_all_work_items_simple(self, iteration_path):
        """Simple method to get all work items without caching"""
        url = f"{self.base_url}/{self.project}/_apis/wit/wiql?api-version=7.0"
        query = {
            "query": f"SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = '{self.project}' AND [System.IterationPath] = '{iteration_path}'"
        }
        response = self.make_post_request(url, json_data=query)
        if response.status_code == 200:
            work_items = response.json().get('workItems', [])
            return [item['id'] for item in work_items]
        else:
            st.error(f"Error getting all work items: {response.status_code}")
            return []

    def get_work_item_details(self, work_item_ids):
        """Get detailed information for work items in batches of 200"""
        if not work_item_ids:
            return []
        
        # Try to get from cache first
        cache_params = {
            'organization': self.organization,
            'project': self.project,
            'work_item_ids': tuple(sorted(work_item_ids))  # Make hashable
        }
        
        cached_data = st.session_state.data_cache.get('work_item_details', cache_params)
        if cached_data is not None:
            # Only show cache message once per session to avoid spam
            if 'work_item_details_cache_shown' not in st.session_state:
                st.success("⚡ Fast loading from cache")
                st.session_state.work_item_details_cache_shown = True
            return cached_data
        
        # If not in cache, fetch from API
        all_details = []
        batch_size = 200
        for i in range(0, len(work_item_ids), batch_size):
            self.rate_limiter.wait_if_needed()  # Rate limit each batch
            batch_ids = work_item_ids[i:i+batch_size]
            ids_str = ",".join(map(str, batch_ids))
            url = f"{self.base_url}/_apis/wit/workitems?ids={ids_str}&$expand=all&api-version=7.1"
            response = self.make_request(url)
            if response.status_code == 200:
                all_details.extend(response.json().get('value', []))
            else:
                st.error(f"Error fetching work item details: {response.status_code}")
        
        # Store in cache
        st.session_state.data_cache.set('work_item_details', cache_params, all_details)
        return all_details
    
    def get_work_item_details_optimized(self, work_item_ids):
        """Optimized version that checks if we already have some IDs cached"""
        if not work_item_ids:
            return []
        
        # Check if we have a superset of these IDs already cached
        cached_work_items = {}
        for cache_key, metadata in st.session_state.data_cache.cache_metadata.items():
            if metadata.get('data_type') == 'work_item_details':
                # Try to decompress and check if it contains our IDs
                try:
                    compressed_data = st.session_state.data_cache.cache.get(cache_key)
                    if compressed_data:
                        cached_data = st.session_state.data_cache._decompress_data(compressed_data)
                        if cached_data:
                            for item in cached_data:
                                cached_work_items[item['id']] = item
                except:
                    continue
        
        # Find missing IDs
        missing_ids = [wid for wid in work_item_ids if wid not in cached_work_items]
        
        if not missing_ids:
            # All IDs are already cached
            result = [cached_work_items[wid] for wid in work_item_ids if wid in cached_work_items]
            if 'work_item_details_cache_shown' not in st.session_state:
                st.success("⚡ Fast loading from cache")
                st.session_state.work_item_details_cache_shown = True
            return result
        
        # Fetch only missing IDs
        if missing_ids:
            missing_details = self.get_work_item_details(missing_ids)
            # Merge with existing cached data
            for item in missing_details:
                cached_work_items[item['id']] = item
        
        # Return requested IDs
        result = [cached_work_items[wid] for wid in work_item_ids if wid in cached_work_items]
        return result
    
    @rate_limited(8)
    def get_child_task_details(self, child_ids):
        """Get details for child tasks"""
        if not child_ids:
            return []
        
        # Try to get from cache first
        cache_params = {
            'organization': self.organization,
            'project': self.project,
            'child_ids': tuple(sorted(child_ids))
        }
        
        cached_data = st.session_state.data_cache.get('child_task_details', cache_params)
        if cached_data is not None:
            # Only show cache message once per session to avoid spam
            if 'child_task_details_cache_shown' not in st.session_state:
                st.success("⚡ Fast loading from cache")
                st.session_state.child_task_details_cache_shown = True
            return cached_data
        
        # If not in cache, fetch from API
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
            result = response.json().get('value', [])
            
            # Store in cache
            st.session_state.data_cache.set('child_task_details', cache_params, result)
            return result
        else:
            st.error(f"Error getting child task details: {response.status_code}")
            return []

    def get_work_item_history(self, work_item_ids, target_date):
        """Get work item history showing actual completed work changes over time"""
        if not work_item_ids:
            return []

        # Try to get from cache first
        cache_params = {
            'organization': self.organization,
            'project': self.project,
            'work_item_ids': tuple(sorted(work_item_ids)),
            'target_date': target_date.isoformat()
        }
        
        cached_data = st.session_state.data_cache.get('work_item_history', cache_params)
        if cached_data is not None:
            # Only show cache message once per session to avoid spam
            if 'work_item_history_cache_shown' not in st.session_state:
                st.success("⚡ Fast loading from cache")
                st.session_state.work_item_history_cache_shown = True
            return cached_data

        task_updates = []
        
        # Get work item details in batch first
        work_item_details = {}
        batch_size = 200
        
        for i in range(0, len(work_item_ids), batch_size):
            try:
                self.check_cancellation()
                self.rate_limiter.wait_if_needed()  # Rate limit each batch
                batch_ids = work_item_ids[i:i+batch_size]
                ids_string = ','.join(map(str, batch_ids))
                
                work_items_url = f"{self.base_url}/_apis/wit/workItems?ids={ids_string}&$expand=all&api-version=7.1"
                response = self.make_request(work_items_url)
                
                if response.status_code == 200:
                    work_items_data = response.json()
                    
                    for work_item in work_items_data.get('value', []):
                        work_item_id = work_item.get('id')
                        fields = work_item.get('fields', {})
                        work_item_details[work_item_id] = {
                            'title': fields.get('System.Title', 'Unknown Task'),
                            'state': fields.get('System.State', 'Unknown'),
                            'assigned_to': fields.get('System.AssignedTo', {}).get('displayName', 'Unassigned'),
                            'changed_date': fields.get('System.ChangedDate', 'Unknown')
                        }
                    
            except Exception as e:
                if "cancelled" in str(e).lower():
                    st.info("🔄 Request cancelled - switching tabs")
                    return []
                else:
                    st.warning(f"Error fetching work item details: {str(e)}")
                    continue

        # Now get the actual work item history for each work item
        # This will show us the progression of completed work over time
        progress_bar = st.progress(0)
        total_work_items = len(work_item_details)
        
        for idx, (work_item_id, work_item_info) in enumerate(work_item_details.items()):
            try:
                self.check_cancellation()
                self.rate_limiter.wait_if_needed()  # Rate limit each history request
                # Get work item history
                history_url = f"{self.base_url}/_apis/wit/workItems/{work_item_id}/updates?api-version=7.1"
                response = requests.get(history_url, headers=self.get_auth_headers())

                if response.status_code == 200:
                    history_data = response.json()
                    
                    # Track completed work progression
                    completed_work_history = []
                    
                    for update in history_data.get('value', []):
                        fields = update.get('fields', {})
                        state_change_field = fields.get('System.ChangedDate', {})
                        update_date = state_change_field.get('newValue', '') if state_change_field else update.get('revisedDate', '')
                        if update_date:
                            update_datetime = datetime.fromisoformat(update_date.replace('Z', '+00:00'))
                            update_date_only = update_datetime.date()
                            
                            fields = update.get('fields', {})
                            completed_work_field = fields.get('Microsoft.VSTS.Scheduling.CompletedWork', {})
                            
                            if completed_work_field:
                                old_value = completed_work_field.get('oldValue', 0) or 0
                                new_value = completed_work_field.get('newValue', 0) or 0
                                
                                if new_value != old_value:  # Only track actual changes
                                    completed_work_history.append({
                                        'date': update_date_only,
                                        'old_value': old_value,
                                        'new_value': new_value,
                                        'change': new_value - old_value,
                                        'revised_by': update.get('revisedBy', {}).get('displayName', 'Unknown'),
                                        'update_time': update_datetime.strftime('%H:%M')
                                    })
                    
                    # Find the completed work value for the target date
                    target_completed = 0
                    target_update = None
                    previous_completed = 0
                    
                    # First, find the completed work value before the target date
                    for history_item in completed_work_history:
                        if history_item['date'] < target_date:
                            previous_completed = history_item['new_value']
                    
                    # Now find if there was an update on the target date
                    for history_item in completed_work_history:
                        if history_item['date'] == target_date:
                            target_completed = history_item['new_value']
                            target_update = history_item
                            break
                    
                    # Calculate hours logged on the specific date
                    hours_logged_on_date = target_completed - previous_completed
                    
                    # Only show if hours were actually logged on this date
                    if hours_logged_on_date > 0:
                        task_updates.append({
                            'Task_ID': work_item_id,
                            'Task_Title': work_item_info['title'],
                            'Team_Member': target_update['revised_by'] if target_update else work_item_info['assigned_to'],
                            'Hours_Updated': hours_logged_on_date,  # Hours logged on this specific date
                            'Old_Completed': previous_completed,  # Previous day's completed work
                            'New_Completed': target_completed,  # New total after this date
                            'Update_Time': target_update['update_time'] if target_update else 'N/A',
                            'Task_State': work_item_info['state']
                        })
                
                # Update progress bar
                progress_bar.progress((idx + 1) / total_work_items)
                
            except Exception as e:
                if "cancelled" in str(e).lower():
                    st.info("🔄 Request cancelled - switching tabs")
                    return []
                else:
                    st.warning(f"Error fetching history for work item {work_item_id}: {str(e)}")
                    continue
        
        progress_bar.empty()
        
        # Store in cache
        st.session_state.data_cache.set('work_item_history', cache_params, task_updates)
        return task_updates

    def get_work_item_history_for_sprint(self, work_item_ids, start_date, end_date):
        """Get work item history for all days in the sprint period"""
        if not work_item_ids:
            return []

        # Try to get from cache first
        cache_params = {
            'organization': self.organization,
            'project': self.project,
            'work_item_ids': tuple(sorted(work_item_ids)),
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat()
        }
        
        cached_data = st.session_state.data_cache.get('work_item_history_sprint', cache_params)
        if cached_data is not None:
            # Only show cache message once per session to avoid spam
            if 'work_item_history_sprint_cache_shown' not in st.session_state:
                st.success("⚡ Fast loading from cache")
                st.session_state.work_item_history_sprint_cache_shown = True
            return cached_data

        task_updates = []
        
        # Get work item details in batch first
        work_item_details = {}
        batch_size = 200
        
        for i in range(0, len(work_item_ids), batch_size):
            try:
                self.check_cancellation()
                self.rate_limiter.wait_if_needed()  # Rate limit each batch
                batch_ids = work_item_ids[i:i+batch_size]
                ids_string = ','.join(map(str, batch_ids))
                
                work_items_url = f"{self.base_url}/_apis/wit/workItems?ids={ids_string}&$expand=all&api-version=7.1"
                response = self.make_request(work_items_url)
                
                if response.status_code == 200:
                    work_items_data = response.json()
                    
                    for work_item in work_items_data.get('value', []):
                        work_item_id = work_item.get('id')
                        fields = work_item.get('fields', {})
                        work_item_details[work_item_id] = {
                            'title': fields.get('System.Title', 'Unknown Task'),
                            'state': fields.get('System.State', 'Unknown'),
                            'assigned_to': fields.get('System.AssignedTo', {}).get('displayName', 'Unassigned')
                        }
                    
            except Exception as e:
                if "cancelled" in str(e).lower():
                    st.info("🔄 Request cancelled - switching tabs")
                    return []
                else:
                    st.warning(f"Error fetching work item details: {str(e)}")
                    continue

        # Now get the actual work item history for each work item
        progress_bar = st.progress(0)
        total_work_items = len(work_item_details)
        
        for idx, (work_item_id, work_item_info) in enumerate(work_item_details.items()):
            try:
                self.check_cancellation()
                self.rate_limiter.wait_if_needed()  # Rate limit each history request
                # Get work item history
                history_url = f"{self.base_url}/_apis/wit/workItems/{work_item_id}/updates?api-version=7.1"
                response = requests.get(history_url, headers=self.get_auth_headers())

                if response.status_code == 200:
                    history_data = response.json()
                    
                    # Track completed work progression
                    completed_work_history = []
                    
                    for update in history_data.get('value', []):
                        fields = update.get('fields', {})
                        state_change_field = fields.get('System.ChangedDate', {})
                        update_date = state_change_field.get('newValue', '') if state_change_field else update.get('revisedDate', '')
                        if update_date:
                            update_datetime = datetime.fromisoformat(update_date.replace('Z', '+00:00'))
                            update_date_only = update_datetime.date()
                            
                            fields = update.get('fields', {})
                            completed_work_field = fields.get('Microsoft.VSTS.Scheduling.CompletedWork', {})
                            
                            if completed_work_field:
                                old_value = completed_work_field.get('oldValue', 0) or 0
                                new_value = completed_work_field.get('newValue', 0) or 0
                                
                                if new_value != old_value:  # Only track actual changes
                                    completed_work_history.append({
                                        'date': update_date_only,
                                        'old_value': old_value,
                                        'new_value': new_value,
                                        'change': new_value - old_value,
                                        'revised_by': update.get('revisedBy', {}).get('displayName', 'Unknown'),
                                        'update_time': update_datetime.strftime('%H:%M')
                                    })
                    
                    # Process all dates in the sprint period
                    for current_date in [start_date + timedelta(days=x) for x in range((end_date - start_date).days + 1)]:
                        # Find all revisions with completed_work changes for this specific date
                        day_revisions = [item for item in completed_work_history if item['date'] == current_date]
                        
                        # If no revisions with completed_work changes for this day, skip it
                        if not day_revisions:
                            continue
                        
                        # Get the first and last revisions for this day
                        first_revision = day_revisions[0]  # First revision of the day
                        last_revision = day_revisions[-1]  # Last revision of the day
                        
                        # Determine previous_completed from first revision
                        if first_revision['old_value'] is not None and first_revision['old_value'] > 0:
                            # First revision has old_value, so this is yesterday's final value
                            previous_completed = first_revision['old_value']
                        else:
                            # First revision has no old_value, so this is the first entry for this task
                            previous_completed = 0
                        
                        # Get final value from last revision
                        target_completed = last_revision['new_value']
                        target_update_time = last_revision['update_time']
                        
                        # If last revision's new_value is 0, skip this day
                        if target_completed == 0:
                            continue
                        
                        # Calculate hours logged on the current date
                        hours_logged_on_date = target_completed - previous_completed
                        
                        # Only add if hours were actually logged on this date
                        if hours_logged_on_date > 0:
                            task_updates.append({
                                'Task_ID': work_item_id,
                                'Task_Title': work_item_info['title'],
                                'Team_Member': work_item_info['assigned_to'],
                                'Date': current_date,
                                'Hours_Updated': hours_logged_on_date,
                                'Old_Completed': previous_completed,
                                'New_Completed': target_completed,
                                'Update_Time': target_update_time,
                                'Task_State': work_item_info['state']
                            })
                
                # Update progress bar
                progress_bar.progress((idx + 1) / total_work_items)
                
            except Exception as e:
                if "cancelled" in str(e).lower():
                    st.info("🔄 Request cancelled - switching tabs")
                    return []
                else:
                    st.warning(f"Error fetching history for work item {work_item_id}: {str(e)}")
                    continue
        
        progress_bar.empty()
        
        # Store in cache
        st.session_state.data_cache.set('work_item_history_sprint', cache_params, task_updates)
        return task_updates

    @rate_limited(8)
    def get_sprint_details(self, team_name, iteration_name):
        """Get sprint start and end dates from Azure DevOps"""
        # Try to get from cache first
        cache_params = {
            'organization': self.organization,
            'project': self.project,
            'team': team_name,
            'iteration': iteration_name
        }
        
        cached_data = st.session_state.data_cache.get('sprint_details', cache_params)
        if cached_data is not None:
            return cached_data
        
        # If not in cache, fetch from API
        try:
            self.check_cancellation()
            iterations_url = f"{self.base_url}/{self.project}/{team_name}/_apis/work/teamsettings/iterations?api-version=7.1"
            response = self.make_request(iterations_url)
            
            if response.status_code == 200:
                iterations_data = response.json()
                
                for iteration in iterations_data.get('value', []):
                    if iteration.get('name') == iteration_name:
                        attributes = iteration.get('attributes', {})
                        start_date = attributes.get('startDate')
                        finish_date = attributes.get('finishDate')
                        
                        if start_date and finish_date:
                            # Convert ISO date strings to datetime objects
                            start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                            finish_dt = datetime.fromisoformat(finish_date.replace('Z', '+00:00'))
                            result = (start_dt.date(), finish_dt.date())
                            
                            # Store in cache
                            st.session_state.data_cache.set('sprint_details', cache_params, result)
                            return result
            
            # Fallback: return current date range if sprint dates not found
            today = datetime.now().date()
            result = (today, today)
            
            # Store in cache
            st.session_state.data_cache.set('sprint_details', cache_params, result)
            return result
            
        except Exception as e:
            if "cancelled" in str(e).lower():
                st.info("🔄 Request cancelled - switching tabs")
            else:
                st.error(f"Error fetching sprint details: {str(e)}")
            today = datetime.now().date()
            return (today, today)

def process_work_item_data(raw_data):
    """Process raw Azure DevOps work item data into flattened DataFrame"""
    processed_data = []
    
    for item in raw_data:
        fields = item.get('fields', {})
        processed_data.append({
            'ID': item.get('id'),
            'Title': fields.get('System.Title'),
            'AssignedTo': fields.get('System.AssignedTo', {}).get('displayName', 'Unassigned'),
            'State': fields.get('System.State'),
            'WorkItemType': fields.get('System.WorkItemType'),
            'IterationPath': fields.get('System.IterationPath', ''),
            'OriginalEstimate': fields.get('Microsoft.VSTS.Scheduling.OriginalEstimate', 0) or 0,
            'RemainingWork': fields.get('Microsoft.VSTS.Scheduling.RemainingWork', 0) or 0,
            'CompletedWork': fields.get('Microsoft.VSTS.Scheduling.CompletedWork', 0) or 0,
            'ChangedDate': fields.get('System.ChangedDate'),
        })
    
    return pd.DataFrame(processed_data)

def process_work_items_with_children(work_items_data):
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

def display_work_items_details_table(df, project_name, api_instance):
    """Display work items details table with filtering options"""
    st.subheader("📋 Work Items Details")
    
    # Create a container for filtering and display
    with st.container():
        # Initialize filter states
        if 'state_filter' not in st.session_state:
            st.session_state.state_filter = 'All'
        if 'assigned_filter' not in st.session_state:
            st.session_state.assigned_filter = 'All'
        if 'iteration_filter' not in st.session_state:
            st.session_state.iteration_filter = 'All'
        
        # Cache unique values to prevent recalculation
        if 'unique_states' not in st.session_state or 'unique_assignees' not in st.session_state or 'unique_iterations' not in st.session_state:
            st.session_state.unique_states = ['All'] + sorted(df['State'].unique())
            st.session_state.unique_assignees = ['All'] + sorted(df['AssignedTo'].unique())
            st.session_state.unique_iterations = ['All'] + sorted(df['IterationPath'].unique())
        
        # Add filtering options with reactive updates
        col1, col2, col3 = st.columns(3)
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
        
        with col3:
            # Get unique iterations and create options
            unique_iterations = st.session_state.unique_iterations
            iteration_index = 0 if st.session_state.iteration_filter == 'All' else unique_iterations.index(st.session_state.iteration_filter) if st.session_state.iteration_filter in unique_iterations else 0
            
            iteration_filter = st.selectbox(
                "Filter by Iteration Path",
                options=unique_iterations,
                index=iteration_index,
                key="iteration_filter"
            )
        
        # Apply filters efficiently using vectorized operations
        filtered_df = df.copy()
        if state_filter != 'All':
            filtered_df = filtered_df[filtered_df['State'] == state_filter]
        if assigned_filter != 'All':
            filtered_df = filtered_df[filtered_df['AssignedTo'] == assigned_filter]
        if iteration_filter != 'All':
            filtered_df = filtered_df[filtered_df['IterationPath'] == iteration_filter]
        
        # Store the filtered data for export
        st.session_state.filtered_data = filtered_df
        
        # Display filtered data with optimized rendering and error handling
        if not filtered_df.empty:
            # Convert ID column to string to remove thousands separator
            filtered_df['ID'] = filtered_df['ID'].astype(str)
            
            # Create a new column with work item URLs for LinkColumn
            # We'll use the ID as both the URL and display text
            filtered_df['WorkItemLink'] = filtered_df['ID'].apply(
                lambda x: f"{get_config_value('AZURE_DEV_URL')}/{api_instance.organization}/{project_name}/_workitems/edit/{x}"
            )
            
            # Remove the original ID column to avoid duplication
            filtered_df = filtered_df.drop('ID', axis=1)
            
            # Reorder columns to put WorkItemLink (ID) first
            columns_order = ['WorkItemLink'] + [col for col in filtered_df.columns if col != 'WorkItemLink']
            filtered_df = filtered_df[columns_order]
            
            # Display the dataframe with clickable links in the ID column
            st.dataframe(
                filtered_df,
                use_container_width=True,
                column_config={
                    "WorkItemLink": st.column_config.LinkColumn(
                        "ID",
                        help="Click to open work item in Azure DevOps",
                        display_text=r".*_workitems/edit/(\d+)$"
                    ),
                    "Title": st.column_config.TextColumn("Title", help="Work Item Title"),
                    "State": st.column_config.TextColumn("State", help="Current State"),
                    "AssignedTo": st.column_config.TextColumn("Assigned To", help="Assigned Person"),
                    "IterationPath": st.column_config.TextColumn("Iteration Path", help="Sprint/Iteration path"),
                    "OriginalEstimate": st.column_config.NumberColumn("Original Estimate (hrs)", help="Original time estimate"),
                    "CompletedWork": st.column_config.NumberColumn("Completed (hrs)", help="Completed work hours"),
                    "RemainingWork": st.column_config.NumberColumn("Remaining (hrs)", help="Remaining work hours")
                },
                hide_index=True
            )
            
            # Add download functionality
            col1, col2, col3 = st.columns([1, 1, 2])
            with col1:
                # Create a copy for export (without the WorkItemLink column)
                export_df = filtered_df.copy()
                
                # Replace WorkItemLink with actual ID values for export
                export_df['ID'] = export_df['WorkItemLink'].str.extract(r'_workitems/edit/(\d+)$')
                export_df = export_df.drop('WorkItemLink', axis=1)
                
                # Reorder columns to put ID first
                export_df = export_df[['ID'] + [col for col in export_df.columns if col != 'ID']]
                
                # Convert to Excel
                import io
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    export_df.to_excel(writer, sheet_name='Work Items', index=False)
                
                buffer.seek(0)
                st.download_button(
                    label="📊 Download as Excel",
                    data=buffer.getvalue(),
                    file_name=f"work_items_{project_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            
            with col2:
                # Convert to CSV
                csv = export_df.to_csv(index=False)
                st.download_button(
                    label="📄 Download as CSV",
                    data=csv,
                    file_name=f"work_items_{project_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv",
                    use_container_width=True
                )
        else:
            st.info("📋 No work items match the selected filters. Try adjusting your filter criteria.")

def display_metrics(df):
    """Display key metrics in cards"""
    if df.empty:
        return
    
    # Calculate work item type-wise counts
    tasks_df = df[df['WorkItemType'] == 'Task']
    requirements_df = df[df['WorkItemType'] == 'Requirement']
    change_requests_df = df[df['WorkItemType'] == 'Change Request']
    bugs_df = df[df['WorkItemType'] == 'Bug']
    features_df = df[df['WorkItemType'] == 'Feature']
    
    # Calculate totals for tasks only (for estimates)
    total_remaining = tasks_df['RemainingWork'].sum()
    total_completed = tasks_df['CompletedWork'].sum()
    total_original_estimate = tasks_df['OriginalEstimate'].sum()
    total_estimate = total_remaining + total_completed
    progress_percentage = (total_completed / total_estimate * 100) if total_estimate > 0 else 0
    
    # Display work item type counts
    st.subheader("📊 Work Item Type Breakdown")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        with st.container():
            st.markdown("""
            <div style="
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                padding: 1.5rem;
                border-radius: 10px;
                text-align: center;
                color: white;
                margin-bottom: 1rem;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            ">
                <h2 style="margin: 0; font-size: 2.5rem; font-weight: bold;">{}</h2>
                <p style="margin: 0; font-size: 1.1rem; opacity: 0.9;">Total Tasks</p>
            </div>
            """.format(len(tasks_df)), unsafe_allow_html=True)
    
    with col2:
        with st.container():
            st.markdown("""
            <div style="
                background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
                padding: 1.5rem;
                border-radius: 10px;
                text-align: center;
                color: white;
                margin-bottom: 1rem;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            ">
                <h2 style="margin: 0; font-size: 2.5rem; font-weight: bold;">{}</h2>
                <p style="margin: 0; font-size: 1.1rem; opacity: 0.9;">Requirements & Change Requests</p>
            </div>
            """.format(len(requirements_df) + len(change_requests_df)), unsafe_allow_html=True)
    
    with col3:
        with st.container():
            st.markdown("""
            <div style="
                background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
                padding: 1.5rem;
                border-radius: 10px;
                text-align: center;
                color: white;
                margin-bottom: 1rem;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            ">
                <h2 style="margin: 0; font-size: 2.5rem; font-weight: bold;">{}</h2>
                <p style="margin: 0; font-size: 1.1rem; opacity: 0.9;">Total Bugs</p>
            </div>
            """.format(len(bugs_df)), unsafe_allow_html=True)
    
    with col4:
        with st.container():
            st.markdown("""
            <div style="
                background: linear-gradient(135deg, #fa709a 0%, #fee140 100%);
                padding: 1.5rem;
                border-radius: 10px;
                text-align: center;
                color: white;
                margin-bottom: 1rem;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            ">
                <h2 style="margin: 0; font-size: 2.5rem; font-weight: bold;">{}</h2>
                <p style="margin: 0; font-size: 1.1rem; opacity: 0.9;">Total Work Items</p>
            </div>
            """.format(len(df)), unsafe_allow_html=True)
    
    # Display task-based estimates
    st.subheader("⏱️ Task-Based Estimates")
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric("Original Estimate (hrs)", f"{total_original_estimate:.1f}")
    
    with col2:
        st.metric("Completed + Remaining (hrs)", f"{total_estimate:.1f}")
    
    with col3:
        st.metric("Completed Work (hrs)", f"{total_completed:.1f}")
    
    with col4:
        st.metric("Remaining Work (hrs)", f"{total_remaining:.1f}")
    
    with col5:
        st.metric("Progress", f"{progress_percentage:.1f}%")
    
    # Progress bar
    st.subheader(f"📈 Sprint Progress: {progress_percentage:.1f}%")
    st.write(f"**{total_completed:.1f}h / {total_estimate:.1f}h completed**")
    st.progress(progress_percentage / 100)
    


def make_work_item_url(id, org, base_url, project):
    """Generate work item URL for link columns"""
    return f"{base_url}/{org}/{project}/_workitems/edit/{id}"

def make_work_item_link(id, org, base_url, project):
    """Legacy function - kept for backward compatibility"""
    url = f"{base_url}/{org}/{project}/_workitems/edit/{id}"
    return f'<a href="{url}" target="_blank">{id}</a>'

def create_daily_progress_spreadsheet(task_updates, start_date, end_date):
    """Transform task updates into a spreadsheet format for daily progress tracking"""
    if not task_updates:
        return None, None
    
    # Create DataFrame from task updates
    df = pd.DataFrame(task_updates)
    
    # Convert Date column to datetime if it's not already
    df['Date'] = pd.to_datetime(df['Date']).dt.date
    
    # Create date range for the sprint
    date_range = [start_date + timedelta(days=x) for x in range((end_date - start_date).days + 1)]
    
    # Get unique team members
    team_members = sorted(df['Team_Member'].unique())
    
    # Create pivot table: Team Member (rows) x Date (columns) x Hours_Updated (values)
    pivot_df = df.pivot_table(
        index='Team_Member',
        columns='Date',
        values='Hours_Updated',
        aggfunc='sum',
        fill_value=0
    )
    
    # Ensure all dates in the sprint are included
    for date in date_range:
        if date not in pivot_df.columns:
            pivot_df[date] = 0
    
    # Sort columns by date
    pivot_df = pivot_df.reindex(sorted(pivot_df.columns), axis=1)
    
    # Format column headers to show actual dates
    date_columns = {}
    for date in pivot_df.columns:
        if isinstance(date, datetime) or hasattr(date, 'strftime'):
            # Format as MM/DD (e.g., "07/16")
            date_columns[date] = date.strftime('%m/%d')
        else:
            # Keep original if not a date
            date_columns[date] = str(date)
    
    pivot_df = pivot_df.rename(columns=date_columns)
    
    # Add individual totals column (after renaming)
    pivot_df['Individual Total'] = pivot_df.sum(axis=1)
    
    return pivot_df, team_members

def show_task_details_dialog(team_member, date, hours):
    """Show task details for a specific team member and date"""
    if 'daily_progress_data' not in st.session_state or st.session_state.daily_progress_data is None:
        st.error("No task data available")
        return
    
    task_updates = st.session_state.daily_progress_data.get('task_updates', [])
    
    # Filter tasks for the specific team member and date
    filtered_tasks = []
    for task in task_updates:
        task_date = pd.to_datetime(task['Date']).date() if isinstance(task['Date'], str) else task['Date']
        if task['Team_Member'] == team_member and task_date == date and task['Hours_Updated'] > 0:
            filtered_tasks.append(task)
    
    if not filtered_tasks:
        st.info(f"No tasks found for {team_member} on {date.strftime('%B %d, %Y')}")
        return
    
    st.write(f"**Tasks for {team_member} on {date.strftime('%B %d, %Y')}**")
    st.write(f"**Total Hours:** {hours}")
    
    # Create a DataFrame for better display
    task_df = pd.DataFrame(filtered_tasks)
    
    # Reorder and rename columns for better display
    display_df = task_df[['Task_ID', 'Task_Title', 'Hours_Updated', 'Update_Time', 'Task_State']].copy()
    display_df.columns = ['Task ID', 'Task Title', 'Hours Logged', 'Update Time', 'Task State']
    
    # Make Task ID clickable by replacing with URLs
    display_df['Task ID'] = display_df['Task ID'].apply(
                            lambda x: make_work_item_url(x, st.session_state.api_instance.organization, get_config_value("AZURE_DEV_URL"), st.session_state.selected_project)
    )
    
    # Display the tasks
    st.dataframe(
        display_df,
        use_container_width=True,
        column_config={
            "Task ID": st.column_config.LinkColumn(
                "Task ID",
                help="Click to open work item in Azure DevOps",
                display_text=r".*_workitems/edit/(\d+)$"  # Extract and display just the ID number
            ),
            "Task Title": st.column_config.TextColumn("Task Title", width="large"),
            "Hours Logged": st.column_config.NumberColumn("Hours Logged", format="%.2f"),
            "Update Time": st.column_config.TextColumn("Update Time"),
            "Task State": st.column_config.TextColumn("Task State")
        },
        hide_index=True
    )

def show_task_details(team_member, date, hours):
    """Show task details for a specific team member and date"""
    # Check if st.dialog is available (Streamlit >= 1.47.0)
    if hasattr(st, 'dialog'):
        # Use dialog if available
        @st.dialog("Task Details")
        def show_dialog():
            show_task_details_dialog(team_member, date, hours)
        show_dialog()
    else:
        # Fallback for older Streamlit versions - use expander
        with st.expander(f"📋 Task Details for {team_member} on {date.strftime('%B %d, %Y')} (Total: {hours}h)", expanded=True):
            show_task_details_dialog(team_member, date, hours)

def main():
    # Using default Streamlit styling
    
    # Show logout button
    show_logout_button()
    
    # Initialize session state for project selection, teams, and iterations
    if 'selected_project' not in st.session_state:
        st.session_state.selected_project = None
    if 'selected_team' not in st.session_state:
        st.session_state.selected_team = None
    if 'selected_iter_name' not in st.session_state:
        st.session_state.selected_iter_name = None
    if 'selected_iter_path' not in st.session_state:
        st.session_state.selected_iter_path = None
    if 'work_item_ids' not in st.session_state:
        st.session_state.work_item_ids = []
    if 'all_work_item_ids' not in st.session_state:
        st.session_state.all_work_item_ids = []
    if 'sprint_data' not in st.session_state:
        st.session_state.sprint_data = None
    if 'work_items_data' not in st.session_state:
        st.session_state.work_items_data = None
    if 'daily_progress_data' not in st.session_state:
        st.session_state.daily_progress_data = None
    if 'parent_child_data' not in st.session_state:
        st.session_state.parent_child_data = None

    # Tab state management for native tabs
    if 'active_tab' not in st.session_state:
        st.session_state.active_tab = "Sprint Metrics"
    if 'api_instance' not in st.session_state:
        st.session_state.api_instance = None
    if 'available_projects' not in st.session_state:
        st.session_state.available_projects = []
    
    # Data loading states for lazy loading
    if 'sprint_data_loaded' not in st.session_state:
        st.session_state.sprint_data_loaded = False
    if 'work_items_data_loaded' not in st.session_state:
        st.session_state.work_items_data_loaded = False
    if 'daily_progress_data_loaded' not in st.session_state:
        st.session_state.daily_progress_data_loaded = False

    # Initialize data cache for compression and caching
    if 'data_cache' not in st.session_state:
        st.session_state.data_cache = DataCache(max_cache_size_mb=50)

    st.title("📊 Sprint Monitoring Dashboard")
    
    # Project Selection
    st.subheader("🏢 Project & Team Selection")
    
    # Initialize API instance for project fetching
    if st.session_state.api_instance is None:
        st.session_state.api_instance = SprintMonitoringAPI()
    
    # Load projects if not already loaded
    if not st.session_state.available_projects:
        with st.spinner("🔄 Loading projects from Azure DevOps..."):
            try:
                projects = st.session_state.api_instance.get_projects()
                if projects:
                    st.session_state.available_projects = projects
                    st.success(f"✅ Found {len(projects)} projects")
                else:
                    st.warning("⚠️ No projects found or error loading projects")
            except Exception as e:
                st.error(f"❌ Error loading projects: {str(e)}")
                st.info("💡 Please check your Azure DevOps PAT and organization settings")
    
    # Create project options for selectbox with default option
    project_options = ["-- Select --"] + [project['name'] for project in st.session_state.available_projects] if st.session_state.available_projects else ["-- Select --"]
    
    # Show message if no projects are available
    if not st.session_state.available_projects:
        st.warning("📋 No projects available. Please check your Azure DevOps connection and try refreshing.")
    
    # Project selection without refresh button
    selected_project = st.selectbox(
        "Select Project",
        options=project_options,
        key="project_select"
    )
    
    if selected_project != st.session_state.selected_project:
        st.session_state.selected_project = selected_project
        st.session_state.selected_team = None
        st.session_state.selected_iter_name = None
        st.session_state.selected_iter_path = None
        st.session_state.work_item_ids = []
        st.session_state.all_work_item_ids = []
        st.session_state.sprint_data = None
        st.session_state.team_summary_data = None
        st.session_state.daily_progress_data = None
        st.session_state.parent_child_data = None
        # Reset loading states when project changes
        st.session_state.sprint_data_loaded = False
        st.session_state.work_items_data_loaded = False
        st.session_state.daily_progress_data_loaded = False
        
        # Reset cache message flags
        cache_flags = [
            'work_item_details_cache_shown',
            'work_item_ids_cache_shown',
            'all_work_item_ids_cache_shown',
            'child_task_details_cache_shown',
            'work_item_history_cache_shown',
            'work_item_history_sprint_cache_shown'
        ]
        for flag in cache_flags:
            if flag in st.session_state:
                del st.session_state[flag]
    
    if selected_project:
        # Initialize API for selected project
        if st.session_state.api_instance is None or st.session_state.selected_project != selected_project:
            st.session_state.api_instance = SprintMonitoringAPI(selected_project)
        api = st.session_state.api_instance
    
    if selected_project and selected_project != "-- Select --":
        # Initialize API for selected project
        if st.session_state.api_instance is None or st.session_state.selected_project != selected_project:
            st.session_state.api_instance = SprintMonitoringAPI(selected_project)
        api = st.session_state.api_instance
        
        # Load teams only when project changes
        if selected_project != st.session_state.get('last_selected_project'):
            with st.spinner(f"🔄 Loading teams for {selected_project}..."):
                teams = api.get_teams()
                st.session_state.available_teams = teams
                st.session_state.last_selected_project = selected_project
                if teams:
                    st.success(f"✅ Found {len(teams)} teams in {selected_project}")
                else:
                    st.warning(f"⚠️ No teams found in {selected_project}")
        else:
            teams = st.session_state.get('available_teams', [])
        
        team_names = ["-- Select --"] + [team['name'] for team in teams] if teams else ["-- Select --"]
        
        selected_team = st.selectbox(
            "Select Team",
            options=team_names,
            key="team_select"
        )
        
        if selected_team != st.session_state.selected_team:
            st.session_state.selected_team = selected_team
            st.session_state.selected_iter_name = None
            st.session_state.selected_iter_path = None
            st.session_state.work_item_ids = []
            st.session_state.all_work_item_ids = []
            st.session_state.sprint_data = None
            st.session_state.team_summary_data = None
            st.session_state.daily_progress_data = None
            st.session_state.parent_child_data = None
            # Reset loading states when team changes
            st.session_state.sprint_data_loaded = False
            st.session_state.work_items_data_loaded = False
            st.session_state.daily_progress_data_loaded = False
            # Clear available iterations when team changes
            if 'available_iterations' in st.session_state:
                del st.session_state.available_iterations
        
        if selected_team and selected_team != "-- Select --":
            # Load iterations automatically when team is selected
            if 'available_iterations' not in st.session_state or not st.session_state.available_iterations:
                with st.spinner(f"🔄 Loading iterations for {selected_team}..."):
                    iterations = api.get_iterations_for_team(selected_team)
                    if iterations:
                        st.session_state.available_iterations = iterations
                        st.success(f"✅ Found {len(iterations)} iterations for {selected_team}")
                    else:
                        st.warning(f"⚠️ No iterations found for {selected_team}")
                        st.session_state.available_iterations = []
            
            # Sprint Selection (only show if iterations are available)
            if st.session_state.available_iterations:
                iteration_names = ["-- Select --"] + [iter['name'] for iter in st.session_state.available_iterations]
                selected_iter_name = st.selectbox(
                    "Select Sprint",
                    options=iteration_names,
                    key="sprint_select"
                )
                
                if selected_iter_name != st.session_state.selected_iter_name:
                    st.session_state.selected_iter_name = selected_iter_name
                    # Find the corresponding path
                    for iter in st.session_state.available_iterations:
                        if iter['name'] == selected_iter_name:
                            st.session_state.selected_iter_path = iter['path']
                            break
                    st.session_state.work_item_ids = []
                    st.session_state.all_work_item_ids = []
                    st.session_state.sprint_data = None
                    st.session_state.team_summary_data = None
                    st.session_state.daily_progress_data = None
                    st.session_state.parent_child_data = None
                    # Reset loading states when sprint changes
                    st.session_state.sprint_data_loaded = False
                    st.session_state.work_items_data_loaded = False
                    st.session_state.daily_progress_data_loaded = False
                
                if selected_iter_name and selected_iter_name != "-- Select --":
                    # Get sprint dates for display
                    start_date, end_date = st.session_state.api_instance.get_sprint_details(selected_team, selected_iter_name)
                    
                    # Display selection info with global refresh button
                    col1, col2 = st.columns([4, 1])
                    with col1:
                        st.info(f"📋 Selected Project: **{selected_project}** | Team: **{selected_team}** | Sprint: **{selected_iter_name}** | 📅 **Sprint Dates:** {start_date.strftime('%B %d, %Y')} - {end_date.strftime('%B %d, %Y')}")
                    with col2:
                        col2a, col2b = st.columns(2)
                        with col2a:
                            if st.button("🔄 Refresh All Data", key="refresh_all_data", use_container_width=True):
                                # Clear all cached data
                                st.session_state.work_item_ids = []
                                st.session_state.all_work_item_ids = []
                                st.session_state.sprint_data = None
                                st.session_state.work_items_data = None
                                st.session_state.daily_progress_data = None
                                st.session_state.sprint_data_loaded = False
                                st.session_state.work_items_data_loaded = False
                                st.session_state.daily_progress_data_loaded = False
                                
                                # Reset cache message flags
                                cache_flags = [
                                    'work_item_details_cache_shown',
                                    'work_item_ids_cache_shown',
                                    'all_work_item_ids_cache_shown',
                                    'child_task_details_cache_shown',
                                    'work_item_history_cache_shown',
                                    'work_item_history_sprint_cache_shown'
                                ]
                                for flag in cache_flags:
                                    if flag in st.session_state:
                                        del st.session_state[flag]
                                
                                st.rerun()
                        with col2b:
                            if st.button("🗑️ Clear API Cache", key="clear_api_cache", use_container_width=True):
                                # Clear API cache
                                if hasattr(st.session_state, 'data_cache'):
                                    st.session_state.data_cache.cache.clear()
                                    st.session_state.data_cache.cache_metadata.clear()
                                st.success("✅ API cache cleared!")
                                st.rerun()
                    
                    # Get work items for selected sprint
                    if not st.session_state.work_item_ids:
                        with st.spinner(f"🔄 Fetching tasks for {selected_iter_name} in team '{selected_team}'..."):
                            work_item_ids = api.get_work_items(st.session_state.selected_iter_path)
                            if work_item_ids:
                                st.session_state.work_item_ids = work_item_ids
                                st.success(f"✅ Found {len(work_item_ids)} tasks in {selected_iter_name} (Team: {selected_team})")
                            else:
                                st.error("❌ Failed to fetch tasks")
                    
                    # Get all work items for Sprint Metrics tab
                    if not st.session_state.all_work_item_ids:
                        with st.spinner(f"🔄 Fetching all work items for {selected_iter_name} in team '{selected_team}'..."):
                            try:
                                all_work_item_ids = api.get_all_work_items(st.session_state.selected_iter_path)
                                if all_work_item_ids:
                                    st.session_state.all_work_item_ids = all_work_item_ids
                                    st.success(f"✅ Found {len(all_work_item_ids)} total work items in {selected_iter_name} (Team: {selected_team})")
                                else:
                                    st.error("❌ Failed to fetch all work items")
                            except AttributeError:
                                # Fallback: use the simpler method
                                st.warning("⚠️ Using fallback method for all work items")
                                all_work_item_ids = api.get_all_work_items_simple(st.session_state.selected_iter_path)
                                if all_work_item_ids:
                                    st.session_state.all_work_item_ids = all_work_item_ids
                                    st.success(f"✅ Found {len(all_work_item_ids)} total work items in {selected_iter_name} (Team: {selected_team})")
                                else:
                                    st.error("❌ Failed to fetch all work items")
                    
                    # Show native tabs only if we have work items
                    if st.session_state.work_item_ids or st.session_state.all_work_item_ids:
                        # Initialize API instance if not exists
                        if st.session_state.api_instance is None:
                            st.session_state.api_instance = SprintMonitoringAPI(selected_project)
                        
                        # Native Tabs Implementation with Lazy Loading
                        tab1, tab2, tab3 = st.tabs([
                            "📊 Sprint Metrics", 
                            "📋 Work Items Details", 
                            "📅 Daily Progress Tracking"
                        ])
                        
                        # Tab 1: Sprint Metrics (Lazy Loading)
                        with tab1:
                            # Check if data needs to be loaded
                            if not st.session_state.sprint_data_loaded or st.session_state.sprint_data is None:
                                # Create progress bar and status text
                                progress_bar = st.progress(0)
                                status_text = st.empty()
                                
                                def update_progress(progress):
                                    progress_bar.progress(progress)
                                
                                def update_status(status):
                                    status_text.text(status)
                                
                                # Initialize progressive loader
                                loader = ProgressiveLoader(chunk_size=50)
                                
                                with st.spinner("🔄 Loading Sprint Metrics..."):
                                    # Use progressive loading for work item details (all work item types)
                                    work_item_details = loader.load_work_items_progressively(
                                        st.session_state.api_instance,
                                        st.session_state.all_work_item_ids,
                                        update_progress,
                                        update_status
                                    )
                                    
                                    if work_item_details:
                                        df = process_work_item_data(work_item_details)
                                        st.session_state.sprint_data = df
                                        st.session_state.work_item_details = work_item_details
                                        
                                        # Process parent-child relationships for work items details
                                        status_text.text("🔄 Processing parent-child relationships...")
                                        progress_bar.progress(0.8)
                                        
                                        # Since we have child tasks in the sprint, we need to find their parent work items
                                        # First, get all child tasks and their parent relationships
                                        child_tasks_in_sprint = work_item_details
                                        st.write(f"📊 Found {len(child_tasks_in_sprint)} work items in the sprint")
                                        
                                        # Collect all parent IDs from child tasks
                                        parent_ids = set()
                                        child_to_parent_mapping = {}
                                        
                                        for child_task in child_tasks_in_sprint:
                                            # Get parent relationships from child tasks
                                            relations = child_task.get('relations', [])
                                            parent_relations = [rel for rel in relations if rel['rel'] == 'System.LinkTypes.Hierarchy-Reverse']
                                            
                                            for relation in parent_relations:
                                                parent_id = int(relation['url'].split('/')[-1])
                                                parent_ids.add(parent_id)
                                                child_to_parent_mapping[child_task['id']] = parent_id
                                        
                                        # Store the mapping in session state for use in task details modal
                                        st.session_state.child_to_parent_mapping = child_to_parent_mapping
                                        
                                        st.write(f"📋 Found {len(parent_ids)} unique parent work items")
                                        
                                        # Get parent work item details
                                        parent_work_items_data = []
                                        if parent_ids:
                                            try:
                                                status_text.text("🔄 Loading parent work item details...")
                                                progress_bar.progress(0.9)
                                                
                                                parent_work_items_data = st.session_state.api_instance.get_work_item_details(list(parent_ids))
                                                st.write(f"📊 Retrieved details for {len(parent_work_items_data)} parent work items")
                                            except Exception as e:
                                                st.error(f"❌ Error fetching parent work item details: {str(e)}")
                                                parent_work_items_data = []
                                        
                                        # Create comprehensive dataset with parent-child aggregation
                                        final_data = []
                                        
                                        for parent_item in parent_work_items_data:
                                            parent_id = parent_item['id']
                                            parent_fields = parent_item.get('fields', {})
                                            
                                            parent_data = {
                                                'ID': parent_id,
                                                'Title': parent_fields.get('System.Title', 'Unknown Title'),
                                                'State': parent_fields.get('System.State', 'Unknown State'),
                                                'AssignedTo': parent_fields.get('System.AssignedTo', {}).get('displayName', 'Unassigned'),
                                                'IterationPath': parent_fields.get('System.IterationPath', ''),
                                                'OriginalEstimate': 0,
                                                'CompletedWork': 0,
                                                'RemainingWork': 0
                                            }
                                            
                                            # Find all child tasks in the sprint that belong to this parent
                                            for child_task in child_tasks_in_sprint:
                                                if child_task['id'] in child_to_parent_mapping and child_to_parent_mapping[child_task['id']] == parent_id:
                                                    child_fields = child_task.get('fields', {})
                                                    parent_data['OriginalEstimate'] += child_fields.get('Microsoft.VSTS.Scheduling.OriginalEstimate', 0) or 0
                                                    parent_data['CompletedWork'] += child_fields.get('Microsoft.VSTS.Scheduling.CompletedWork', 0) or 0
                                                    parent_data['RemainingWork'] += child_fields.get('Microsoft.VSTS.Scheduling.RemainingWork', 0) or 0
                                            
                                            # Only include parent if it has children in the sprint
                                            if parent_data['OriginalEstimate'] > 0 or parent_data['CompletedWork'] > 0 or parent_data['RemainingWork'] > 0:
                                                final_data.append(parent_data)
                                        
                                        # Create DataFrame for work items details
                                        if final_data:
                                            parent_child_df = pd.DataFrame(final_data)
                                            st.session_state.parent_child_data = parent_child_df
                                            st.write(f"✅ Created work items details table with {len(final_data)} parent work items")
                                        else:
                                            st.session_state.parent_child_data = None
                                            st.info("📋 No parent work items with child tasks in this sprint found")
                                        
                                        progress_bar.progress(1.0)
                                        status_text.text("✅ Sprint Metrics loaded successfully!")
                                        
                                        st.session_state.sprint_data_loaded = True
                                
                                # Clear progress indicators
                                progress_bar.empty()
                                status_text.empty()
                            
                            # Display Sprint Metrics (data is now loaded)
                            if st.session_state.sprint_data is not None:
                                display_metrics(st.session_state.sprint_data)
                                
                                # Team Summary Table
                                st.subheader("👥 Team Summary")
                                
                                # Filter for tasks only
                                df_tasks = st.session_state.sprint_data[
                                    st.session_state.sprint_data['WorkItemType'] == 'Task'
                                ].copy()
                                
                                if not df_tasks.empty:
                                    # Separate assigned and unassigned work items
                                    assigned_tasks = df_tasks[df_tasks['AssignedTo'] != 'Unassigned']
                                    unassigned_tasks = df_tasks[df_tasks['AssignedTo'] == 'Unassigned']
                                    
                                    # Team summary for assigned tasks
                                    if not assigned_tasks.empty:
                                        team_summary = assigned_tasks.groupby('AssignedTo').agg({
                                            'ID': 'count',
                                            'OriginalEstimate': 'sum',
                                            'CompletedWork': 'sum',
                                            'RemainingWork': 'sum'
                                        }).reset_index()
                                        
                                        team_summary.columns = ['Team Member', 'Task Count', 'Original Estimate (hrs)', 'Completed Work (hrs)', 'Remaining Work (hrs)']
                                        
                                        # Reset index for numbering starting from 1
                                        team_summary = team_summary.reset_index(drop=True)
                                        team_summary.index = team_summary.index + 1
                                        
                                        st.write("**Assigned Tasks:**")
                                        # Display team summary table
                                        st.dataframe(team_summary, use_container_width=True)
                                    
                                    # Unassigned tasks summary
                                    if not unassigned_tasks.empty:
                                        st.write("**Unassigned Tasks:**")
                                        unassigned_summary = {
                                            'Task Count': len(unassigned_tasks),
                                            'Original Estimate (hrs)': unassigned_tasks['OriginalEstimate'].sum(),
                                            'Completed Work (hrs)': unassigned_tasks['CompletedWork'].sum(),
                                            'Remaining Work (hrs)': unassigned_tasks['RemainingWork'].sum()
                                        }
                                        st.write(f"Total Unassigned: {unassigned_summary['Task Count']} tasks, "
                                                f"{unassigned_summary['Original Estimate (hrs)']:.1f} hrs estimated, "
                                                f"{unassigned_summary['Completed Work (hrs)']:.1f} hrs completed")
                                
                                # Display Work Items Details Table (Parent-Child Aggregated)
                                if st.session_state.parent_child_data is not None and not st.session_state.parent_child_data.empty:
                                    display_work_items_details_table(st.session_state.parent_child_data, selected_project, st.session_state.api_instance)
                                else:
                                    st.info("📋 No parent work items with child tasks found in this sprint.")
                                    st.info("💡 This could mean:")
                                    st.info("   • The child tasks in the sprint don't have parent work items linked to them")
                                    st.info("   • The parent-child relationships are not configured properly")
                                    st.info("   • The parent work items are not accessible or don't exist")
                        
                        # Tab 2: Work Items Details (Lazy Loading)
                        with tab2:
                            # Check if data needs to be loaded
                            if not st.session_state.work_items_data_loaded or st.session_state.work_items_data is None:
                                # Create progress bar and status text
                                progress_bar = st.progress(0)
                                status_text = st.empty()
                                
                                def update_progress(progress):
                                    progress_bar.progress(progress)
                                
                                def update_status(status):
                                    status_text.text(status)
                                
                                # Initialize progressive loader
                                loader = ProgressiveLoader(chunk_size=50)
                                
                                with st.spinner("🔄 Loading Work Items Details..."):
                                    # Use progressive loading for work item details (all work item types)
                                    work_item_details = loader.load_work_items_progressively(
                                        st.session_state.api_instance,
                                        st.session_state.all_work_item_ids,
                                        update_progress,
                                        update_status
                                    )
                                    
                                    if work_item_details:
                                        df = process_work_item_data(work_item_details)
                                        st.session_state.work_items_data = df
                                        st.session_state.work_items_data_loaded = True
                                
                                # Clear progress indicators
                                progress_bar.empty()
                                status_text.empty()
                            
                            # Display Work Items Details (data is now loaded)
                            if st.session_state.work_items_data is not None:
                                # Work Items Details Table
                                st.subheader("📋 Work Items Details")
                                
                                # Add filtering options
                                col1, col2, col3, col4, col5 = st.columns(5)
                                with col1:
                                    state_filter = st.selectbox(
                                        "Filter by State",
                                        options=['All'] + sorted(st.session_state.work_items_data['State'].unique()),
                                        key="state_filter_work_items"
                                    )
                                
                                with col2:
                                    work_item_type_filter = st.selectbox(
                                        "Filter by Work Item Type",
                                        options=['All'] + sorted(st.session_state.work_items_data['WorkItemType'].unique()),
                                        key="work_item_type_filter_work_items"
                                    )
                                
                                with col3:
                                    assignee_filter = st.selectbox(
                                        "Filter by Assigned To",
                                        options=['All'] + sorted(st.session_state.work_items_data['AssignedTo'].unique()),
                                        key="assignee_filter_work_items"
                                    )
                                
                                with col4:
                                    iteration_filter = st.selectbox(
                                        "Filter by Iteration Path",
                                        options=['All'] + sorted(st.session_state.work_items_data['IterationPath'].unique()),
                                        key="iteration_filter_work_items"
                                    )
                                
                                with col5:
                                    # Add a spacer or additional filter if needed
                                    st.write("")  # Empty space for balance
                                
                                # Apply filters
                                filtered_data = st.session_state.work_items_data.copy()
                                if state_filter != 'All':
                                    filtered_data = filtered_data[filtered_data['State'] == state_filter]
                                if work_item_type_filter != 'All':
                                    filtered_data = filtered_data[filtered_data['WorkItemType'] == work_item_type_filter]
                                if assignee_filter != 'All':
                                    filtered_data = filtered_data[filtered_data['AssignedTo'] == assignee_filter]
                                if iteration_filter != 'All':
                                    filtered_data = filtered_data[filtered_data['IterationPath'] == iteration_filter]
                                
                                # Replace ID column with URLs for proper linking
                                filtered_data['ID'] = filtered_data['ID'].apply(
                                    lambda x: make_work_item_url(x, st.session_state.api_instance.organization, get_config_value("AZURE_DEV_URL"), selected_project)
                                )
                                
                                # Remove date columns and reset index for numbering
                                filtered_data = filtered_data.drop(['ChangedDate', 'Date'], axis=1, errors='ignore')
                                filtered_data = filtered_data.reset_index(drop=True)
                                filtered_data.index = filtered_data.index + 1
                                
                                # Display filtered data
                                if not filtered_data.empty:
                                    st.write(f"Showing {len(filtered_data)} of {len(st.session_state.work_items_data)} work items")
                                    # Display work items table with proper link configuration
                                    st.dataframe(
                                        filtered_data,
                                        use_container_width=True,
                                        column_config={
                                            "ID": st.column_config.LinkColumn(
                                                "ID",
                                                help="Click to open work item in Azure DevOps",
                                                display_text=r".*_workitems/edit/(\d+)$"  # Extract and display just the ID number
                                            )
                                        }
                                    )
                                else:
                                    st.info("📋 No work items match the selected filters.")
                        
                        # Tab 3: Daily Progress Tracking (Lazy Loading)
                        with tab3:
                            # Check if data needs to be loaded
                            if not st.session_state.daily_progress_data_loaded or st.session_state.daily_progress_data is None:
                                # Get sprint details (this will show cache message only once)
                                start_date, end_date = st.session_state.api_instance.get_sprint_details(selected_team, selected_iter_name)
                                
                                # Create progress bar and status text
                                progress_bar = st.progress(0)
                                status_text = st.empty()
                                
                                def update_progress(progress):
                                    progress_bar.progress(progress)
                                
                                def update_status(status):
                                    status_text.text(status)
                                
                                # Initialize progressive loader for individual work item processing
                                loader = ProgressiveLoader(chunk_size=1)
                                
                                # Show loading message (will be cleared after completion)
                                loading_message = st.info("🔄 **Loading fresh data from Azure DevOps API...** This may take a few minutes for large sprints.")
                                
                                # Fetch work item history for entire sprint period using progressive loading (tasks only)
                                try:
                                    task_updates = loader.load_work_item_history_progressively(
                                        st.session_state.api_instance,
                                        st.session_state.work_item_ids,  # Only tasks for daily progress tracking
                                        start_date,
                                        end_date,
                                        update_progress,
                                        update_status
                                    )
                                    
                                    if task_updates:
                                        # Debug: Check for specific task 63091
                                        task_63091_found = any(task['Task_ID'] == 63091 for task in task_updates)
                                        if not task_63091_found:
                                            st.warning(f"⚠️ Debug: Task 63091 not found in task_updates. Checking if it's in work_item_ids...")
                                            if 63091 in st.session_state.work_item_ids:
                                                st.warning(f"⚠️ Debug: Task 63091 is in work_item_ids but not in task_updates. This suggests no completed work changes were found.")
                                            else:
                                                st.warning(f"⚠️ Debug: Task 63091 is NOT in work_item_ids. This suggests it's not being fetched by the API query.")
                                        
                                        # Check if we need to include missing tasks with completed work
                                        missing_tasks = []
                                        all_work_item_details = st.session_state.api_instance.get_work_item_details(st.session_state.work_item_ids)
                                        
                                        for item in all_work_item_details:
                                            fields = item.get('fields', {})
                                            completed_work = fields.get('Microsoft.VSTS.Scheduling.CompletedWork', 0) or 0
                                            task_id = item.get('id')
                                            
                                            # Check if this task has completed work but is not in task_updates
                                            if completed_work > 0 and not any(task['Task_ID'] == task_id for task in task_updates):
                                                # This task has completed work but no history changes were detected
                                                # Add it as a manual entry for today
                                                missing_tasks.append({
                                                    'Task_ID': task_id,
                                                    'Task_Title': fields.get('System.Title', 'Unknown Task'),
                                                    'Team_Member': fields.get('System.AssignedTo', {}).get('displayName', 'Unassigned'),
                                                    'Date': datetime.now().date(),
                                                    'Hours_Updated': completed_work,
                                                    'Old_Completed': 0,
                                                    'New_Completed': completed_work,
                                                    'Update_Time': 'Manual Entry',
                                                    'Task_State': fields.get('System.State', 'Unknown')
                                                })
                                        
                                        if missing_tasks:
                                            st.warning(f"⚠️ Found {len(missing_tasks)} tasks with completed work but no history changes. Adding them manually.")
                                            task_updates.extend(missing_tasks)
                                        
                                        # Create spreadsheet format
                                        pivot_df, team_members = create_daily_progress_spreadsheet(task_updates, start_date, end_date)
                                        
                                        # Debug: Show all tasks with completed work
                                        if st.checkbox("🔍 Show Debug Information", key="show_debug_info"):
                                            st.write(f"📅 **Current Date:** {datetime.now().date()}")
                                            st.write(f"📅 **Sprint Start:** {start_date}")
                                            st.write(f"📅 **Sprint End:** {end_date}")
                                            st.write(f"📊 **Total Tasks Processed:** {len(st.session_state.work_item_ids)}")
                                            st.write(f"📊 **Tasks with Updates:** {len(task_updates)}")
                                            
                                            st.subheader("🔍 Debug: All Tasks with Completed Work")
                                            
                                            # Get all work item details to check completed work
                                            all_work_item_details = st.session_state.api_instance.get_work_item_details(st.session_state.work_item_ids)
                                            
                                            debug_data = []
                                            for item in all_work_item_details:
                                                fields = item.get('fields', {})
                                                completed_work = fields.get('Microsoft.VSTS.Scheduling.CompletedWork', 0) or 0
                                                if completed_work > 0:
                                                    debug_data.append({
                                                        'Task_ID': item.get('id'),
                                                        'Title': fields.get('System.Title', 'Unknown'),
                                                        'Assigned_To': fields.get('System.AssignedTo', {}).get('displayName', 'Unassigned'),
                                                        'Completed_Work': completed_work,
                                                        'State': fields.get('System.State', 'Unknown'),
                                                        'In_Task_Updates': any(task['Task_ID'] == item.get('id') for task in task_updates)
                                                    })
                                            
                                            if debug_data:
                                                debug_df = pd.DataFrame(debug_data)
                                                st.dataframe(debug_df, use_container_width=True)
                                            else:
                                                st.info("No tasks with completed work found in the work item details.")
                                            
                                            # Additional debug: Check all work items (not just tasks)
                                            st.subheader("🔍 Debug: All Work Items (including non-tasks)")
                                            all_work_items_details = st.session_state.api_instance.get_work_item_details(st.session_state.all_work_item_ids)
                                            
                                            all_debug_data = []
                                            for item in all_work_items_details:
                                                fields = item.get('fields', {})
                                                work_item_type = fields.get('System.WorkItemType', 'Unknown')
                                                completed_work = fields.get('Microsoft.VSTS.Scheduling.CompletedWork', 0) or 0
                                                if completed_work > 0:
                                                    all_debug_data.append({
                                                        'Work_Item_ID': item.get('id'),
                                                        'Type': work_item_type,
                                                        'Title': fields.get('System.Title', 'Unknown'),
                                                        'Assigned_To': fields.get('System.AssignedTo', {}).get('displayName', 'Unassigned'),
                                                        'Completed_Work': completed_work,
                                                        'State': fields.get('System.State', 'Unknown'),
                                                        'In_Task_List': item.get('id') in st.session_state.work_item_ids
                                                    })
                                            
                                            if all_debug_data:
                                                all_debug_df = pd.DataFrame(all_debug_data)
                                                st.dataframe(all_debug_df, use_container_width=True)
                                            else:
                                                st.info("No work items with completed work found.")
                                        
                                        if pivot_df is not None and not pivot_df.empty:
                                            # Store data in session state with timestamp
                                            st.session_state.daily_progress_data = {
                                                'pivot_df': pivot_df,
                                                'team_members': team_members,
                                                'task_updates': task_updates,
                                                'cached_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                            }
                                            st.session_state.daily_progress_data_loaded = True
                                            
                                        else:
                                            st.info("📋 No work was logged during this sprint period.")
                                            st.info("💡 This could mean:")
                                            st.info("   • No work was logged during the sprint")
                                            st.info("   • Work items were updated but not the 'Completed Work' field")
                                            st.info("   • The sprint doesn't have historical data")
                                            
                                    else:
                                        st.info("📋 No work was logged during this sprint period.")
                                        st.info("💡 This could mean:")
                                        st.info("   • No work was logged during the sprint")
                                        st.info("   • Work items were updated but not the 'Completed Work' field")
                                        st.info("   • The sprint doesn't have historical data")
                                        
                                        # Show some debugging information
                                        st.subheader("🔍 Debug Information")
                                        st.write(f"**Sprint Start:** {start_date.strftime('%B %d, %Y')}")
                                        st.write(f"**Sprint End:** {end_date.strftime('%B %d, %Y')}")
                                        st.write(f"**Total Work Items in Sprint:** {len(st.session_state.work_item_ids)}")
                                        
                                except Exception as e:
                                    st.error(f"❌ Error fetching daily progress data: {str(e)}")
                                
                                # Clear loading message and progress indicators
                                loading_message.empty()
                                progress_bar.empty()
                                status_text.empty()
                            
                            # Display Daily Progress (data is now loaded)
                            if st.session_state.daily_progress_data is not None:
                                st.subheader("📅 Daily Progress Tracking")
                                
                                # Show cache info with timestamp (only once, not duplicated)
                                cached_at = st.session_state.daily_progress_data.get('cached_at')
                                if cached_at:
                                    st.success(f"✅ **Displaying cached data** (cached at {cached_at}) - Fast loading! Use '🔄 Refresh All Data' to fetch latest data from API.")
                                else:
                                    st.success("✅ **Displaying cached data** - Fast loading! Use '🔄 Refresh All Data' to fetch latest data from API.")
                                
                                pivot_df = st.session_state.daily_progress_data['pivot_df']
                                team_members = st.session_state.daily_progress_data['team_members']
                                
                                # Add Export to Excel functionality
                                col_export, col_info = st.columns([1, 4])
                                with col_export:
                                    # Create Excel export functionality
                                    def create_excel_export():
                                        from io import BytesIO
                                        
                                        # Create a BytesIO buffer for the Excel file
                                        excel_buffer = BytesIO()
                                        
                                        # Create Excel writer object
                                        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                                            # Export the daily progress data
                                            export_df = pivot_df.copy()
                                            export_df.to_excel(writer, sheet_name='Daily Progress', index=True)
                                            
                                            # Create summary sheet
                                            daily_columns = [col for col in pivot_df.columns if col != 'Individual Total']
                                            data_without_totals = pivot_df[~pivot_df.index.str.contains('Total', case=False, na=False)] if hasattr(pivot_df.index, 'str') else pivot_df
                                            daily_data = data_without_totals[daily_columns]
                                            
                                            summary_data = {
                                                'Metric': ['Total Hours Logged', 'Active Days', 'Team Members', 'Avg Hours/Day'],
                                                'Value': [
                                                    f"{daily_data.sum().sum():.2f}",
                                                    str((daily_data.sum() > 0).sum()),
                                                    str(len(team_members)),
                                                    f"{daily_data.sum().sum() / (daily_data.sum() > 0).sum() if (daily_data.sum() > 0).sum() > 0 else 0:.2f}"
                                                ]
                                            }
                                            summary_df = pd.DataFrame(summary_data)
                                            summary_df.to_excel(writer, sheet_name='Summary', index=False)
                                        
                                        excel_buffer.seek(0)
                                        return excel_buffer
                                    
                                    # Create download button
                                    excel_data = create_excel_export()
                                    current_date = datetime.now().strftime("%Y%m%d_%H%M%S")
                                    filename = f"daily_progress_tracking_{current_date}.xlsx"
                                    
                                    st.download_button(
                                        label="📥 Export to Excel",
                                        data=excel_data,
                                        file_name=filename,
                                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                                    )
                                
                                with col_info:
                                    st.info("💡 **Tip:** Click on any hours value in the table above to view detailed task information for that team member and date.")
                                
                                # Get the date mapping for reverse lookup
                                date_mapping = {}
                                for date in pivot_df.columns:
                                    if date != 'Individual Total':
                                        # Parse the date string (format: MM/DD)
                                        try:
                                            month, day = map(int, date.split('/'))
                                            # Find the original date for this day number
                                            for original_date in [start_date + timedelta(days=x) for x in range((end_date - start_date).days + 1)]:
                                                if original_date.month == month and original_date.day == day:
                                                    date_mapping[date] = original_date
                                                    break
                                        except (ValueError, AttributeError):
                                            # Skip if date parsing fails
                                            continue
                                
                                # Create a copy of the dataframe for AgGrid (filter out any existing Total rows from cached data)
                                pivot_df_clean = pivot_df[~pivot_df.index.str.contains('Total', case=False, na=False)] if hasattr(pivot_df.index, 'str') else pivot_df
                                display_df = pivot_df_clean.reset_index()
                                
                                # Calculate total row for pinned bottom
                                total_row = pivot_df_clean.sum()
                                total_row_dict = {display_df.columns[0]: 'Total'}  # Team Member column
                                for col in display_df.columns[1:]:  # All other columns
                                    if col in total_row:
                                        total_row_dict[col] = total_row[col]
                                    else:
                                        total_row_dict[col] = 0
                                
                                # Get the actual column name for team member (it might be the index name)
                                team_member_col = display_df.columns[0]  # First column after reset_index
                                
                                # Configure AgGrid options
                                gb = GridOptionsBuilder.from_dataframe(display_df)
                                gb.configure_default_column(
                                    resizable=True,
                                    filterable=True,
                                    sorteable=True,
                                    editable=False
                                )
                                
                                # Configure the Team Member column
                                gb.configure_column(team_member_col, pinned="left", width=200)
                                
                                # Get task updates data for JavaScript
                                task_updates = st.session_state.daily_progress_data.get('task_updates', []) if st.session_state.daily_progress_data else []
                                
                                # Get parent work item mapping for tasks
                                parent_mapping = {}
                                if hasattr(st.session_state, 'parent_child_data') and st.session_state.parent_child_data is not None:
                                    # Get the child_to_parent_mapping from session state if available
                                    if hasattr(st.session_state, 'child_to_parent_mapping'):
                                        parent_mapping = st.session_state.child_to_parent_mapping
                                    else:
                                        # Create parent mapping from work item details if available
                                        if hasattr(st.session_state, 'work_item_details'):
                                            for work_item in st.session_state.work_item_details:
                                                task_id = work_item.get('id')
                                                relations = work_item.get('relations', [])
                                                parent_relations = [rel for rel in relations if rel['rel'] == 'System.LinkTypes.Hierarchy-Reverse']
                                                if parent_relations:
                                                    parent_id = int(parent_relations[0]['url'].split('/')[-1])
                                                    parent_mapping[task_id] = parent_id
                                
                                # Create a mapping of task-wise hours by team member and date
                                # Structure (before JSON): { member: { 'MM/DD': { 'taskId': hours_sum } } }
                                task_mapping = {}
                                for task in task_updates:
                                    task_date = pd.to_datetime(task['Date']).date() if isinstance(task['Date'], str) else task['Date']
                                    date_key = task_date.strftime('%m/%d')  # Use MM/DD format to match column headers
                                    member_key = task['Team_Member']
                                    task_id = str(task.get('Task_ID'))
                                    try:
                                        task_hours = float(task.get('Hours_Updated', 0) or 0)
                                    except Exception:
                                        task_hours = 0.0
                                    
                                    if member_key not in task_mapping:
                                        task_mapping[member_key] = {}
                                    if date_key not in task_mapping[member_key]:
                                        task_mapping[member_key][date_key] = {}
                                    
                                    existing_hours = task_mapping[member_key][date_key].get(task_id, 0.0)
                                    task_mapping[member_key][date_key][task_id] = float(existing_hours) + task_hours
                                
                                # Convert inner dicts to list of {id, hours, parentId}
                                for _member, _dates in task_mapping.items():
                                    for _date_key, _id_to_hours in _dates.items():
                                        if isinstance(_id_to_hours, dict):
                                            task_mapping[_member][_date_key] = [
                                                {
                                                    'id': tid, 
                                                    'hours': round(hrs, 2),
                                                    'parentId': parent_mapping.get(int(tid), None)
                                                } for tid, hrs in _id_to_hours.items()
                                            ]
                                
                                # Convert task mapping to JSON for JavaScript
                                import json
                                task_mapping_json = json.dumps(task_mapping)
                                
                                # Configure each date column to be clickable
                                for col in display_df.columns:
                                    if col != team_member_col and col != 'Individual Total':
                                        # Create a custom cell renderer for clickable hours
                                        cell_renderer = JsCode("""
                                        class ClickableCellRenderer {
                                            init(params) {
                                                this.eGui = document.createElement('span');
                                                this.eGui.innerText = params.value;
                                                
                                                if (params.value > 0) {
                                                    this.eGui.style.cursor = 'pointer';
                                                    this.eGui.style.color = '#262730';
                                                    this.eGui.addEventListener('click', (event) => {
                                                        event.stopPropagation(); // Prevent row selection
                                                        var teamMember = params.data['""" + team_member_col + """'];
                                                        var day = '""" + col + """';
                                                        var hours = params.value;
                                                        var taskDetails = this.getTasksForMemberAndDay(teamMember, day);
                                                        
                                                        this.ensureModalStyles();
                                                        this.openModal(teamMember, day, hours, taskDetails);
                                                    });
                                                } else {
                                                    this.eGui.style.color = '#999';
                                                }
                                            }
                                            
                                            getGui() {
                                                return this.eGui;
                                            }
                                            
                                            refresh(params) {
                                                return false;
                                            }
                                            
                                            getTasksForMemberAndDay(teamMember, day) {
                                                var taskMapping = """ + task_mapping_json + """;
                                                if (taskMapping[teamMember] && taskMapping[teamMember][day]) {
                                                    return taskMapping[teamMember][day];
                                                }
                                                return [];
                                            }
                                            
                                            ensureModalStyles() {
                                                if (document.getElementById('sb-modal-styles')) return;
                                                var style = document.createElement('style');
                                                style.id = 'sb-modal-styles';
                                                style.textContent = `
                                                    .sb-modal-overlay {
                                                        position: fixed;
                                                        top: 0;
                                                        left: 0;
                                                        width: 100vw;
                                                        height: 100vh;
                                                        background: rgba(0,0,0,0.45);
                                                        display: none;
                                                        align-items: center;
                                                        justify-content: center;
                                                        z-index: 2147483000;
                                                    }
                                                    .sb-modal {
                                                        background: #ffffff;
                                                        color: #262730;
                                                        border-radius: 8px;
                                                        box-shadow: 0 10px 30px rgba(0,0,0,0.2);
                                                        width: min(640px, 95vw);
                                                        max-height: 90vh;
                                                        display: flex;
                                                        flex-direction: column;
                                                        overflow: hidden;
                                                        border: 1px solid #e5e7eb;
                                                    }
                                                    .sb-modal-header {
                                                        display: flex;
                                                        align-items: center;
                                                        justify-content: space-between;
                                                        padding: 12px 16px;
                                                        border-bottom: 1px solid #f1f1f1;
                                                        font-weight: 600;
                                                    }
                                                    .sb-modal-content {
                                                        padding: 16px;
                                                        overflow: auto;
                                                        max-height: 75vh;
                                                    }
                                                    .sb-modal-close {
                                                        border: none;
                                                        background: transparent;
                                                        font-size: 18px;
                                                        cursor: pointer;
                                                        color: #6b7280;
                                                    }
                                                    .sb-modal-list { margin: 0; padding-left: 16px; }
                                                    .sb-badge {
                                                        display: inline-block;
                                                        background: #f3f4f6;
                                                        color: #111827;
                                                        border-radius: 9999px;
                                                        padding: 2px 8px;
                                                        font-size: 12px;
                                                        margin-left: 6px;
                                                    }
                                                `;
                                                document.head.appendChild(style);
                                            }
                                            
                                            openModal(teamMember, day, hours, taskDetails) {
                                                let overlay = document.getElementById('sb-modal-overlay');
                                                if (!overlay) {
                                                    overlay = document.createElement('div');
                                                    overlay.id = 'sb-modal-overlay';
                                                    overlay.className = 'sb-modal-overlay';
                                                    
                                                    const modal = document.createElement('div');
                                                    modal.id = 'sb-modal';
                                                    modal.className = 'sb-modal';
                                                    
                                                    const header = document.createElement('div');
                                                    header.className = 'sb-modal-header';
                                                    const title = document.createElement('div');
                                                    title.textContent = 'Task Details';
                                                    const closeBtn = document.createElement('button');
                                                    closeBtn.className = 'sb-modal-close';
                                                    closeBtn.innerHTML = '&times;';
                                                    closeBtn.addEventListener('click', () => this.closeModal());
                                                    header.appendChild(title);
                                                    header.appendChild(closeBtn);
                                                    
                                                    const content = document.createElement('div');
                                                    content.className = 'sb-modal-content';
                                                    content.id = 'sb-modal-content';
                                                    
                                                    modal.appendChild(header);
                                                    modal.appendChild(content);
                                                    overlay.appendChild(modal);
                                                    
                                                    overlay.addEventListener('click', (e) => {
                                                        if (e.target === overlay) this.closeModal();
                                                    });
                                                    
                                                    document.body.appendChild(overlay);
                                                }
                                                
                                                // Update content
                                                const contentEl = document.getElementById('sb-modal-content');
                                                if (contentEl) {
                                                    contentEl.innerHTML = '';
                                                    const p1 = document.createElement('p');
                                                    p1.innerHTML = `<strong>Team Member:</strong> ${this.escapeHtml(teamMember)}`;
                                                    const p2 = document.createElement('p');
                                                    p2.innerHTML = `<strong>Date:</strong> ${this.escapeHtml(day)} <span class="sb-badge">Total: ${this.escapeHtml(String(hours))} h</span>`;
                                                    const p3 = document.createElement('p');
                                                    p3.innerHTML = `<strong>Task-wise hours:</strong>`;
                                                    
                                                    if (Array.isArray(taskDetails) && taskDetails.length > 0) {
                                                        const table = document.createElement('table');
                                                        table.className = 'sb-modal-table';
                                                        table.style.width = '100%';
                                                        table.style.borderCollapse = 'collapse';
                                                        table.style.marginTop = '8px';
                                                        
                                                        // Create table header
                                                        const thead = document.createElement('thead');
                                                        const headerRow = document.createElement('tr');
                                                        headerRow.style.backgroundColor = '#f8f9fa';
                                                        headerRow.style.borderBottom = '2px solid #dee2e6';
                                                        
                                                        const headers = ['Parent ID', 'Task ID', 'Hours'];
                                                        headers.forEach(headerText => {
                                                            const th = document.createElement('th');
                                                            th.textContent = headerText;
                                                            th.style.padding = '8px 12px';
                                                            th.style.textAlign = 'left';
                                                            th.style.fontWeight = '600';
                                                            th.style.borderBottom = '1px solid #dee2e6';
                                                            headerRow.appendChild(th);
                                                        });
                                                        thead.appendChild(headerRow);
                                                        table.appendChild(thead);
                                                        
                                                        // Create table body
                                                        const tbody = document.createElement('tbody');
                                                        taskDetails.forEach((t) => {
                                                            const tr = document.createElement('tr');
                                                            tr.style.borderBottom = '1px solid #e9ecef';
                                                            
                                                            const parentIdText = t.parentId ? this.escapeHtml(String(t.parentId)) : 'N/A';
                                                            const idText = this.escapeHtml(String(t.id));
                                                            const hrsText = this.escapeHtml(String(t.hours));
                                                            
                                                            const td1 = document.createElement('td');
                                                            td1.style.padding = '8px 12px';
                                                            if (t.parentId) {
                                                                const link = document.createElement('a');
                                                                link.href = `https://dev.azure.com/${this.getOrganization()}/${this.getProject()}/_workitems/edit/${t.parentId}`;
                                                                link.target = '_blank';
                                                                link.textContent = parentIdText;
                                                                link.style.textDecoration = 'none';
                                                                link.style.color = '#0078d4';
                                                                link.style.fontWeight = '600';
                                                                td1.appendChild(link);
                                                            } else {
                                                                td1.textContent = 'N/A';
                                                                td1.style.color = '#6c757d';
                                                                td1.style.fontStyle = 'italic';
                                                            }
                                                            
                                                            const td2 = document.createElement('td');
                                                            td2.style.padding = '8px 12px';
                                                            const link = document.createElement('a');
                                                            link.href = `https://dev.azure.com/${this.getOrganization()}/${this.getProject()}/_workitems/edit/${t.id}`;
                                                            link.target = '_blank';
                                                            link.textContent = idText;
                                                            link.style.textDecoration = 'none';
                                                            link.style.color = '#0078d4';
                                                            link.style.fontWeight = '600';
                                                            td2.appendChild(link);
                                                            
                                                            const td3 = document.createElement('td');
                                                            td3.textContent = hrsText + ' h';
                                                            td3.style.padding = '8px 12px';
                                                            td3.style.fontWeight = '600';
                                                            td3.style.color = '#28a745';
                                                            
                                                            tr.appendChild(td1);
                                                            tr.appendChild(td2);
                                                            tr.appendChild(td3);
                                                            tbody.appendChild(tr);
                                                        });
                                                        table.appendChild(tbody);
                                                        
                                                        contentEl.appendChild(p1);
                                                        contentEl.appendChild(p2);
                                                        contentEl.appendChild(p3);
                                                        contentEl.appendChild(table);
                                                    } else {
                                                        const p4 = document.createElement('p');
                                                        p4.textContent = 'No tasks found';
                                                        p4.style.color = '#6c757d';
                                                        p4.style.fontStyle = 'italic';
                                                        
                                                        contentEl.appendChild(p1);
                                                        contentEl.appendChild(p2);
                                                        contentEl.appendChild(p3);
                                                        contentEl.appendChild(p4);
                                                    }
                                                }
                                                
                                                overlay.style.display = 'flex';
                                                document.body.style.overflow = 'hidden';
                                            }
                                            
                                            closeModal() {
                                                const overlay = document.getElementById('sb-modal-overlay');
                                                if (overlay) overlay.style.display = 'none';
                                                document.body.style.overflow = '';
                                            }
                                            
                                            escapeHtml(unsafe) {
                                                return String(unsafe)
                                                    .replace(/&/g, '&amp;')
                                                    .replace(/</g, '&lt;')
                                                    .replace(/>/g, '&gt;')
                                                    .replace(/"/g, '&quot;')
                                                    .replace(/'/g, '&#039;');
                                            }
                                            
                                            getOrganization() {
                                                return '""" + st.session_state.api_instance.organization + """';
                                            }
                                            
                                            getProject() {
                                                return '""" + st.session_state.api_instance.project + """';
                                            }
                                        }
                                        """)
                                        
                                        gb.configure_column(
                                            col,
                                            cellRenderer=cell_renderer,
                                            width=100,
                                            headerName=col
                                        )
                                
                                # Configure the Total column
                                gb.configure_column("Individual Total", width=120, headerName="Total")
                                
                                # Build grid options for cell-level interaction
                                gb.configure_grid_options(
                                    domLayout='normal',
                                    suppressRowClickSelection=True,
                                    suppressCellSelection=False,
                                    pinnedBottomRowData=[total_row_dict]
                                )
                                grid_options = gb.build()
                                
                                # Display AgGrid
                                grid_response = AgGrid(
                                    display_df,
                                    gridOptions=grid_options,
                                    data_return_mode=DataReturnMode.AS_INPUT,
                                    update_mode=GridUpdateMode.MODEL_CHANGED,
                                    fit_columns_on_grid_load=True,
                                    theme="streamlit",
                                    allow_unsafe_jscode=True,
                                    custom_css={
                                        ".ag-row-hover": {"background-color": "lightblue !important"},
                                        ".ag-row-selected": {"background-color": "#e3f2fd !important"}
                                    }
                                )
                                                                
                                # Show summary metrics
                                st.subheader("📈 Summary Metrics")
                                col1, col2, col3, col4 = st.columns(4)
                                
                                # Exclude 'Individual Total' column from calculations and filter out any Total rows
                                daily_columns = [col for col in pivot_df.columns if col != 'Individual Total']
                                # Filter out any 'Total' rows that might exist in cached data
                                data_without_totals = pivot_df[~pivot_df.index.str.contains('Total', case=False, na=False)] if hasattr(pivot_df.index, 'str') else pivot_df
                                daily_data = data_without_totals[daily_columns]
                                
                                with col1:
                                    total_hours = daily_data.sum().sum()
                                    st.metric("Total Hours Logged", f"{total_hours:.2f}")
                                
                                with col2:
                                    daily_totals = daily_data.sum()
                                    active_days = (daily_totals > 0).sum()
                                    st.metric("Active Days", active_days)
                                
                                with col3:
                                    team_member_count = len(team_members)
                                    st.metric("Team Members", team_member_count)
                                
                                with col4:
                                    avg_hours_per_day = total_hours / active_days if active_days > 0 else 0
                                    st.metric("Avg Hours/Day", f"{avg_hours_per_day:.2f}")

# Authentication functions
def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against its hash"""
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def load_user_credentials():
    """Load user credentials from Streamlit secrets or environment variables"""
    users = {}
    
    # Check Streamlit secrets first (for Streamlit Cloud)
    try:
        if hasattr(st, 'secrets'):
            for key in st.secrets:
                if key.startswith('AUTH_USER_'):
                    username = key[10:].lower()  # Remove 'AUTH_USER_' prefix
                    users[username] = st.secrets[key]
    except:
        pass
    
    # Fallback to environment variables (for local development)
    if not users:
        for key, value in os.environ.items():
            if key.startswith('AUTH_USER_'):
                username = key[10:].lower()  # Remove 'AUTH_USER_' prefix
                users[username] = value
    
    # Require proper configuration
    if not users:
        st.error("❌ No authentication users configured!")
        st.info("💡 **For Streamlit Cloud:** Add AUTH_USER_ADMIN=<bcrypt_hash> to your app secrets")
        st.info("💡 **For Local Development:** Set AUTH_USER_<username> environment variables")
        st.info("🔧 Use generate_password_hash.py to create password hashes.")
        st.stop()
    
    return users

def authenticate_user(username: str, password: str) -> bool:
    """Authenticate a user with username and password"""
    users = load_user_credentials()
    username_lower = username.lower()
    
    if username_lower in users:
        return verify_password(password, users[username_lower])
    return False

def show_login_form():
    """Display the login form"""
    st.set_page_config(
        page_title="Scrum Buddy - Login",
        page_icon="🔐",
        layout="wide"
    )
    
    # Reduce top spacing by using a container
    container = st.container()
    
    with container:
        # Center the content
        col1, col2 = st.columns([2, 2])
            
        with col1:
            st.title("🧠 Scrum Buddy")
            st.subheader("Sprint Monitoring Dashboard")
            
            st.markdown("---")

            st.write("📊 Real-time Sprint Analytics")
            st.write("📈 Team Performance Insights") 
            st.write("🔄 Azure DevOps Integration")
            st.write("📱 Modern Responsive Design")
        
        with col2:
            st.markdown("### Please Login")
            
            with st.form("login_form"):
                username = st.text_input("Username", placeholder="Enter your username")
                password = st.text_input("Password", type="password", placeholder="Enter your password")
                submit_button = st.form_submit_button("Sign In", use_container_width=True)
                
                if submit_button:
                    if username and password:
                        if authenticate_user(username, password):
                            st.success("Login successful! Redirecting...")
                            save_authentication(username)
                        else:
                            st.error("Invalid username or password")
                    else:
                        st.error("Please enter both username and password")
        


def logout_user():
    """Logout the current user"""
    clear_authentication()

def check_authentication():
    """Check if user is authenticated"""
    return st.session_state.get('authenticated', False)

def show_logout_button():
    """Show logout button in sidebar"""
    with st.sidebar:
        st.markdown("---")
        st.markdown(f"👤 **Logged in as:** {st.session_state.get('username', 'Unknown')}")
        if st.button("🚪 Logout", use_container_width=True):
            logout_user()

def generate_session_token(username):
    """Generate a simple session token"""
    import hashlib
    import time
    timestamp = str(int(time.time()))
    token_string = f"{username}:{timestamp}"
    return hashlib.md5(token_string.encode()).hexdigest()

def validate_session_token(token, username):
    """Validate session token (basic validation)"""
    # In a real app, you'd store tokens in a database with expiration
    # For this demo, we'll just check if it's a valid MD5 hash
    return len(token) == 32 and token.isalnum()

def save_authentication(username):
    """Save authentication using URL redirect"""
    token = generate_session_token(username)
    st.session_state.auth_token = token
    st.session_state.authenticated = True
    st.session_state.username = username
    # Redirect with token in URL
    st.query_params.token = token
    st.query_params.user = username
    st.rerun()

def clear_authentication():
    """Clear authentication"""
    st.session_state.authenticated = False
    st.session_state.username = None
    if 'auth_token' in st.session_state:
        del st.session_state.auth_token
    # Clear query params
    st.query_params.clear()
    st.rerun()

def restore_authentication():
    """Restore authentication from URL parameters"""
    query_params = st.query_params
    if 'token' in query_params and 'user' in query_params:
        token = query_params['token']
        username = query_params['user']
        
        if validate_session_token(token, username):
            st.session_state.authenticated = True
            st.session_state.username = username
            st.session_state.auth_token = token
            return True
    return False

if __name__ == "__main__":
    # Initialize authentication session state
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
    if 'username' not in st.session_state:
        st.session_state.username = None
    
    # Try to restore authentication from URL parameters
    if not st.session_state.authenticated:
        restore_authentication()
    
    # Check authentication
    if not check_authentication():
        show_login_form()
    else:
        # Set page config for authenticated users
        st.set_page_config(
            page_title="Sprint Monitoring Dashboard",
            page_icon="🧠",
            layout="wide"
        )
        main() 