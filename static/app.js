// Multi-Pass Catalog Extractor - Database-backed
const API_BASE = '';

let currentDocumentId = null;
let currentPassId = null;
let pollInterval = null;

// Method descriptions
const METHOD_DESCRIPTIONS = {
    'auto_multi_pass': 'AI-powered 2-pass: Claude Vision (standard) → Enhanced prompt (low-confidence pages). Cost: ~$0.02-0.05/page',
    'claude_vision': 'Single-pass Claude AI Vision extraction. Most accurate, cost: ~$0.015-0.03/page',
    'text_direct': 'PDFplumber text extraction (NO OCR) - for native PDF text only (free, fast)',
    'ocr_table': 'OCR with table detection - best for structured catalog data (free)',
    'ocr_plain': 'OCR without table detection - for unstructured text (free)',
    'ocr_aggressive': 'High-DPI OCR with aggressive preprocessing - for poor quality scans (free)',
    'hybrid': 'Combines multiple OCR methods sequentially (free)'
};

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    setupFileUpload();
    setupMethodSelector();
    loadRecentDocuments();
});

// Setup method selector
function setupMethodSelector() {
    const select = document.getElementById('extractionMethod');
    const description = document.getElementById('methodDescription');
    
    select.addEventListener('change', (e) => {
        description.textContent = METHOD_DESCRIPTIONS[e.target.value] || '';
    });
}

// File upload setup
function setupFileUpload() {
    const fileInput = document.getElementById('fileInput');
    const uploadBox = document.getElementById('uploadBox');
    let isUploading = false;

    uploadBox.addEventListener('click', (e) => {
        e.stopPropagation();
        if (!isUploading) {
            fileInput.click();
        }
    });

    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0 && !isUploading) {
            isUploading = true;
            uploadFile(e.target.files[0]).finally(() => {
                isUploading = false;
                fileInput.value = ''; // Reset input
            });
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
        e.stopPropagation();
        uploadBox.classList.remove('dragover');
        
        if (e.dataTransfer.files.length > 0 && !isUploading) {
            const file = e.dataTransfer.files[0];
            if (file.type === 'application/pdf') {
                isUploading = true;
                uploadFile(file).finally(() => {
                    isUploading = false;
                });
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

    // Check for raw text mode
    const rawTextMode = document.getElementById('rawTextMode').checked;
    
    if (rawTextMode) {
        // Raw text extraction - direct CSV download
        try {
            const response = await fetch(`${API_BASE}/api/extract-raw-text`, {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                throw new Error('Raw text extraction failed');
            }

            // Get stats from headers
            const totalLines = response.headers.get('X-Total-Lines');
            const totalChars = response.headers.get('X-Total-Characters');
            const pages = response.headers.get('X-Pages');

            // Download CSV
            const blob = await response.blob();
            const downloadUrl = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = downloadUrl;
            a.download = `raw_text_${file.name.replace('.pdf', '')}_${Date.now()}.csv`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(downloadUrl);

            alert(`✅ Raw text extracted!\n\n📄 ${pages} pages\n📝 ${totalLines} lines\n🔤 ${totalChars} characters\n\nCSV downloaded successfully!`);

        } catch (error) {
            console.error('Raw text extraction error:', error);
            alert('❌ Error extracting raw text: ' + error.message);
        }
        return;
    }

    // Normal extraction (with DB)
    const method = document.getElementById('extractionMethod').value;
    const startPage = document.getElementById('startPage').value || 0;
    const endPage = document.getElementById('endPage').value;
    const dpi = document.getElementById('dpi').value || 300;
    const minConfidence = document.getElementById('minConfidence').value || 50;
    const forceOcr = document.getElementById('forceOcr').checked;
    const debugMode = document.getElementById('debugMode').checked;

    // Build URL
    let url = `${API_BASE}/api/documents/upload?method=${method}&start_page=${startPage}&dpi=${dpi}&min_confidence=${minConfidence}&force_ocr=${forceOcr}&debug_mode=${debugMode}`;
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

        const result = await response.json();
        currentDocumentId = result.document_id;
        currentPassId = result.pass_id;

        // Show processing section
        document.getElementById('processingSection').style.display = 'block';
        document.getElementById('resultsSection').style.display = 'none';
        setTimeout(() => scrollToSection('processingSection'), 100);

        // Start polling
        startPolling();

    } catch (error) {
        alert('Error uploading file: ' + error.message);
    }
}

// Start polling
function startPolling() {
    if (pollInterval) {
        clearInterval(pollInterval);
    }

    pollInterval = setInterval(async () => {
        await updatePassStatus();
    }, 2000); // Poll every 2 seconds
}

// Update pass status
async function updatePassStatus() {
    if (!currentDocumentId) return;

    try {
        // Check document status to see all passes
        const docResponse = await fetch(`${API_BASE}/api/documents/${currentDocumentId}`);
        const doc = await docResponse.json();

        // Update progress
        const progressFill = document.getElementById('progressFill');
        const progressText = document.getElementById('progressText');
        const progressPercent = document.getElementById('progressPercent');

        // Check all passes for the document
        const allPasses = doc.passes || [];
        const completedPasses = allPasses.filter(p => p.status === 'completed').length;
        const failedPasses = allPasses.filter(p => p.status === 'failed').length;
        const processingPasses = allPasses.filter(p => p.status === 'processing').length;
        const totalPasses = allPasses.length;
        
        // Calculate overall progress
        let totalItems = 0;
        allPasses.forEach(p => {
            totalItems += p.items_extracted || 0;
        });

        // Update UI based on status
        if (processingPasses > 0) {
            // Still processing
            const progress = totalPasses > 0 ? (completedPasses / totalPasses) * 100 : 0;
            progressFill.style.width = progress + '%';
            progressPercent.textContent = Math.round(progress) + '%';
            progressText.textContent = `Pass ${completedPasses + 1}/${totalPasses} - ${totalItems} items found`;
        } else if (completedPasses > 0 && processingPasses === 0 && failedPasses < totalPasses) {
            // All passes completed successfully
            progressFill.style.width = '100%';
            progressPercent.textContent = '100%';
            progressText.textContent = `Complete! ${totalItems} items extracted`;
            
            clearInterval(pollInterval);
            await showResults(currentDocumentId);
            await loadRecentDocuments();
        } else if (failedPasses === totalPasses) {
            // All passes failed
            clearInterval(pollInterval);
            progressText.textContent = 'Error: All extraction passes failed';
            progressText.style.color = '#ef4444';
            await loadRecentDocuments();
        }

    } catch (error) {
        console.error('Error polling status:', error);
    }
}

// Show results
async function showResults(documentId) {
    try {
        // Get document details
        const docResponse = await fetch(`${API_BASE}/api/documents/${documentId}`);
        const doc = await docResponse.json();

        // Get consolidated items
        const itemsResponse = await fetch(`${API_BASE}/api/documents/${documentId}/items/consolidated`);
        const items = await itemsResponse.json();

        // Show results section
        document.getElementById('processingSection').style.display = 'none';
        document.getElementById('resultsSection').style.display = 'block';
        setTimeout(() => scrollToSection('resultsSection'), 100);

        // Show passes
        if (doc.passes && doc.passes.length > 0) {
            showPasses(doc.passes);
        }

        // Calculate stats
        const totalItems = items.length;
        const withPrices = items.filter(r => r.price_value !== null).length;
        const withPartNumbers = items.filter(r => r.part_number).length;
        const avgConfidence = totalItems > 0 
            ? items.reduce((sum, r) => sum + (r.avg_confidence || 0), 0) / totalItems 
            : 0;

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
        tableBody.innerHTML = items.map(item => `
            <tr>
                <td>${item.brand_code || '-'}</td>
                <td><strong>${item.part_number || '-'}</strong></td>
                <td>${item.price_type || '-'}</td>
                <td>${item.price_value ? '$' + item.price_value.toFixed(2) : '-'}</td>
                <td>${item.currency}</td>
                <td>${item.page}</td>
                <td>
                    <span class="confidence-badge ${getConfidenceClass(item.avg_confidence)}">
                        ${item.avg_confidence.toFixed(1)}%
                    </span>
                </td>
                <td>${item.source_count} pass${item.source_count > 1 ? 'es' : ''}</td>
            </tr>
        `).join('');

        // Setup download button
        document.getElementById('downloadCsvBtn').onclick = () => {
            window.location.href = `${API_BASE}/api/documents/${documentId}/export/csv`;
        };

        // Setup new pass button
        const newPassBtn = document.getElementById('newPassBtn');
        newPassBtn.style.display = 'inline-flex';
        newPassBtn.onclick = () => showNewPassDialog(documentId);

    } catch (error) {
        console.error('Error loading results:', error);
        alert('Error loading results: ' + error.message);
    }
}

// Show passes
function showPasses(passes) {
    const passesOverview = document.getElementById('passesOverview');
    const passesList = document.getElementById('passesList');

    passesOverview.style.display = 'block';

    passesList.innerHTML = passes.map(pass => `
        <div class="pass-item">
            <div class="pass-info">
                <div class="pass-title">
                    Pass #${pass.pass_number}: ${pass.method.replace('_', ' ').toUpperCase()}
                </div>
                <div class="pass-meta">
                    ${pass.items_extracted} items | 
                    ${pass.avg_confidence ? pass.avg_confidence.toFixed(1) + '% confidence | ' : ''}
                    ${pass.processing_time ? pass.processing_time.toFixed(1) + 's' : ''}
                </div>
            </div>
            <span class="job-status status-${pass.status}">${pass.status}</span>
        </div>
    `).join('');
}

// Show new pass dialog
function showNewPassDialog(documentId) {
    const method = prompt(
        'Select extraction method:\n\n' +
        '1. text_direct - Fast text extraction\n' +
        '2. ocr_table - OCR with tables\n' +
        '3. ocr_plain - OCR plain text\n' +
        '4. ocr_aggressive - Thorough OCR\n' +
        '5. hybrid - All methods\n\n' +
        'Enter method name:',
        'ocr_aggressive'
    );

    if (method) {
        createNewPass(documentId, method);
    }
}

// Create new pass
async function createNewPass(documentId, method) {
    try {
        const response = await fetch(`${API_BASE}/api/documents/${documentId}/passes`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                method: method,
                start_page: 0,
                end_page: null,
                dpi: 300,
                min_confidence: 50.0,
                force_ocr: false,
                debug_mode: false
            })
        });

        if (!response.ok) {
            throw new Error('Failed to create pass');
        }

        const result = await response.json();
        currentPassId = result.pass_id;

        // Show processing
        document.getElementById('resultsSection').style.display = 'none';
        document.getElementById('processingSection').style.display = 'block';
        scrollToSection('processingSection');

        // Start polling
        startPolling();

    } catch (error) {
        alert('Error creating new pass: ' + error.message);
    }
}

// Get confidence class
function getConfidenceClass(confidence) {
    if (confidence >= 70) return 'confidence-high';
    if (confidence >= 50) return 'confidence-medium';
    return 'confidence-low';
}

// Smooth scroll
function scrollToSection(sectionId) {
    const section = document.getElementById(sectionId);
    if (section) {
        section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

// Load recent documents
async function loadRecentDocuments() {
    try {
        const response = await fetch(`${API_BASE}/api/documents`);
        const docs = await response.json();

        const jobsList = document.getElementById('jobsList');
        
        if (docs.length === 0) {
            jobsList.innerHTML = '<p style="color: #666;">No documents yet</p>';
            return;
        }

        jobsList.innerHTML = docs.map(doc => `
            <div class="job-card">
                <div class="job-header">
                    <div class="job-name">${doc.filename}</div>
                    <span class="job-status status-completed">${doc.pass_count} pass${doc.pass_count > 1 ? 'es' : ''}</span>
                </div>
                <div class="job-details">
                    ${doc.total_pages} pages | Uploaded: ${new Date(doc.upload_date).toLocaleString()}
                </div>
                <div class="job-actions">
                    <button class="btn btn-success" onclick="viewDocument(${doc.id})">
                        View Results
                    </button>
                    <button class="btn btn-primary" onclick="showNewPassDialog(${doc.id})">
                        + New Pass
                    </button>
                </div>
            </div>
        `).join('');

    } catch (error) {
        console.error('Error loading documents:', error);
    }
}

// View document
async function viewDocument(documentId) {
    currentDocumentId = documentId;
    await showResults(documentId);
}

