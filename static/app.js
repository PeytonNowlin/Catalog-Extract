// API base URL
const API_BASE = '';

// Current job ID
let currentJobId = null;
let pollInterval = null;

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    setupFileUpload();
    loadRecentJobs();
});

// File upload setup
function setupFileUpload() {
    const fileInput = document.getElementById('fileInput');
    const uploadBox = document.getElementById('uploadBox');

    // Click to upload
    uploadBox.addEventListener('click', () => {
        fileInput.click();
    });

    // File selected
    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            uploadFile(e.target.files[0]);
        }
    });

    // Drag and drop
    uploadBox.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadBox.classList.add('dragover');
    });

    uploadBox.addEventListener('dragleave', () => {
        uploadBox.classList.remove('dragover');
    });

    uploadBox.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadBox.classList.remove('dragover');
        
        if (e.dataTransfer.files.length > 0) {
            const file = e.dataTransfer.files[0];
            if (file.type === 'application/pdf') {
                uploadFile(file);
            } else {
                alert('Please upload a PDF file');
            }
        }
    });
}

// Upload file
async function uploadFile(file) {
    const formData = new FormData();
    formData.append('file', file);

    // Get options
    const startPage = document.getElementById('startPage').value || 0;
    const endPage = document.getElementById('endPage').value;
    const dpi = document.getElementById('dpi').value || 300;
    const minConfidence = document.getElementById('minConfidence').value || 50;
    const forceOcr = document.getElementById('forceOcr').checked;
    const debugMode = document.getElementById('debugMode').checked;

    // Build URL with query params
    let url = `${API_BASE}/api/upload?start_page=${startPage}&dpi=${dpi}&min_confidence=${minConfidence}&force_ocr=${forceOcr}&debug_mode=${debugMode}`;
    if (endPage) {
        url += `&end_page=${endPage}`;
    }

    try {
        const response = await fetch(url, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            throw new Error('Upload failed');
        }

        const job = await response.json();
        currentJobId = job.job_id;

        // Show processing section
        document.getElementById('processingSection').style.display = 'block';
        document.getElementById('resultsSection').style.display = 'none';
        
        // Scroll to processing section
        setTimeout(() => scrollToSection('processingSection'), 100);

        // Start polling for status
        startPolling();

    } catch (error) {
        alert('Error uploading file: ' + error.message);
    }
}

// Start polling job status
function startPolling() {
    if (pollInterval) {
        clearInterval(pollInterval);
    }

    pollInterval = setInterval(async () => {
        await updateJobStatus();
    }, 1000); // Poll every second
}

// Update job status
async function updateJobStatus() {
    if (!currentJobId) return;

    try {
        const response = await fetch(`${API_BASE}/api/jobs/${currentJobId}`);
        const job = await response.json();

        // Update progress bar
        const progressFill = document.getElementById('progressFill');
        const progressText = document.getElementById('progressText');

        progressFill.style.width = job.progress + '%';
        progressFill.textContent = Math.round(job.progress) + '%';
        progressText.textContent = job.message;

        // Check if completed
        if (job.status === 'completed') {
            clearInterval(pollInterval);
            await showResults(currentJobId);
            await loadRecentJobs();
        } else if (job.status === 'failed') {
            clearInterval(pollInterval);
            progressText.textContent = 'Error: ' + (job.error || 'Processing failed');
            progressText.style.color = '#ef4444';
            await loadRecentJobs();
        }

    } catch (error) {
        console.error('Error polling job status:', error);
    }
}

// Show results
async function showResults(jobId) {
    try {
        // Get results
        const response = await fetch(`${API_BASE}/api/jobs/${jobId}/results`);
        const results = await response.json();

        // Show results section
        document.getElementById('processingSection').style.display = 'none';
        document.getElementById('resultsSection').style.display = 'block';

        // Calculate stats
        const totalItems = results.length;
        const withPrices = results.filter(r => r.price_value !== null).length;
        const withPartNumbers = results.filter(r => r.part_number).length;
        const avgConfidence = results.reduce((sum, r) => sum + r.confidence, 0) / totalItems || 0;

        // Display stats
        const statsHtml = `
            <div class="stat-card">
                <div class="stat-value">${totalItems}</div>
                <div class="stat-label">Total Items</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">${withPartNumbers}</div>
                <div class="stat-label">With Part Numbers</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">${withPrices}</div>
                <div class="stat-label">With Prices</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">${avgConfidence.toFixed(1)}%</div>
                <div class="stat-label">Avg Confidence</div>
            </div>
        `;
        document.getElementById('statsGrid').innerHTML = statsHtml;

        // Display results table
        const tableBody = document.getElementById('resultsTableBody');
        tableBody.innerHTML = results.map(item => `
            <tr>
                <td>${item.brand_code || '-'}</td>
                <td><strong>${item.part_number || '-'}</strong></td>
                <td>${item.price_type || '-'}</td>
                <td>${item.price_value ? '$' + item.price_value.toFixed(2) : '-'}</td>
                <td>${item.currency}</td>
                <td>${item.page}</td>
                <td>
                    <span class="confidence-badge ${getConfidenceClass(item.confidence)}">
                        ${item.confidence.toFixed(1)}%
                    </span>
                </td>
            </tr>
        `).join('');

        // Setup download buttons
        document.getElementById('downloadCsvBtn').onclick = () => {
            window.location.href = `${API_BASE}/api/jobs/${jobId}/download/csv`;
        };

        document.getElementById('downloadSummaryBtn').onclick = () => {
            window.location.href = `${API_BASE}/api/jobs/${jobId}/download/summary`;
        };

    } catch (error) {
        console.error('Error loading results:', error);
        alert('Error loading results: ' + error.message);
    }
}

// Get confidence class
function getConfidenceClass(confidence) {
    if (confidence >= 70) return 'confidence-high';
    if (confidence >= 50) return 'confidence-medium';
    return 'confidence-low';
}

// Smooth scroll to section
function scrollToSection(sectionId) {
    const section = document.getElementById(sectionId);
    if (section) {
        section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

// Load recent jobs
async function loadRecentJobs() {
    try {
        const response = await fetch(`${API_BASE}/api/jobs?limit=10`);
        const jobs = await response.json();

        const jobsList = document.getElementById('jobsList');
        
        if (jobs.length === 0) {
            jobsList.innerHTML = '<p style="color: #666;">No recent jobs</p>';
            return;
        }

        jobsList.innerHTML = jobs.map(job => `
            <div class="job-card">
                <div class="job-header">
                    <div class="job-name">${job.pdf_name}</div>
                    <span class="job-status status-${job.status}">${job.status.toUpperCase()}</span>
                </div>
                <div class="job-details">
                    ${job.items_extracted > 0 ? `${job.items_extracted} items extracted | ` : ''}
                    ${new Date(job.created_at).toLocaleString()}
                    ${job.total_pages ? ` | ${job.total_pages} pages` : ''}
                </div>
                <div class="job-actions">
                    ${job.status === 'completed' ? `
                        <button class="btn btn-success" onclick="viewResults('${job.job_id}')">
                            View Results
                        </button>
                        <button class="btn btn-secondary" onclick="downloadCsv('${job.job_id}')">
                            Download CSV
                        </button>
                    ` : ''}
                    ${job.status === 'processing' ? `
                        <button class="btn btn-primary" onclick="viewJob('${job.job_id}')">
                            View Progress
                        </button>
                    ` : ''}
                    <button class="btn btn-danger" onclick="deleteJob('${job.job_id}')">
                        Delete
                    </button>
                </div>
            </div>
        `).join('');

    } catch (error) {
        console.error('Error loading jobs:', error);
    }
}

// View results
async function viewResults(jobId) {
    currentJobId = jobId;
    await showResults(jobId);
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// View job progress
async function viewJob(jobId) {
    currentJobId = jobId;
    document.getElementById('processingSection').style.display = 'block';
    document.getElementById('resultsSection').style.display = 'none';
    startPolling();
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// Download CSV
function downloadCsv(jobId) {
    window.location.href = `${API_BASE}/api/jobs/${jobId}/download/csv`;
}

// Delete job
async function deleteJob(jobId) {
    if (!confirm('Are you sure you want to delete this job?')) {
        return;
    }

    try {
        await fetch(`${API_BASE}/api/jobs/${jobId}`, {
            method: 'DELETE'
        });
        
        if (currentJobId === jobId) {
            currentJobId = null;
            if (pollInterval) {
                clearInterval(pollInterval);
            }
        }
        
        await loadRecentJobs();
    } catch (error) {
        alert('Error deleting job: ' + error.message);
    }
}

