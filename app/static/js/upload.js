/* Second Brain - Batch File Upload Handler */

function initBatchUpload(dropzoneId, inputId, previewId, btnId, resultId) {
    var dropzone = document.getElementById(dropzoneId);
    var input = document.getElementById(inputId);
    var preview = document.getElementById(previewId);
    var btn = document.getElementById(btnId);
    if (!dropzone || !input) return;

    // Click to open file dialog
    dropzone.addEventListener('click', function() {
        input.click();
    });

    // Drag events
    ['dragenter', 'dragover'].forEach(function(eventName) {
        dropzone.addEventListener(eventName, function(e) {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.add('dragover');
        });
    });

    ['dragleave', 'drop'].forEach(function(eventName) {
        dropzone.addEventListener(eventName, function(e) {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.remove('dragover');
        });
    });

    dropzone.addEventListener('drop', function(e) {
        var files = e.dataTransfer.files;
        if (files.length > 0) {
            input.files = files;
            showFileList(files, preview, btn);
        }
    });

    input.addEventListener('change', function() {
        if (input.files.length > 0) {
            showFileList(input.files, preview, btn);
        }
    });
}

function showFileList(files, previewEl, btn) {
    if (!previewEl) return;
    var html = '<div class="mt-3">';
    for (var i = 0; i < files.length; i++) {
        var f = files[i];
        var icon = f.type === 'application/pdf' ? '📄' : '🖼️';
        var size = (f.size / 1024).toFixed(1);
        html += '<div class="d-flex align-items-center gap-2 mb-2 file-item" data-index="' + i + '">' +
            '<span class="fs-5">' + icon + '</span>' +
            '<div class="flex-grow-1">' +
            '<div class="fw-medium small file-name"></div>' +
            '<div class="text-muted" style="font-size:.75rem">' + size + ' KB</div>' +
            '</div>' +
            '<span class="badge bg-secondary file-status">Oczekuje</span>' +
            '</div>';
    }
    html += '</div>';
    previewEl.innerHTML = html;
    // Set filenames via textContent to prevent XSS
    previewEl.querySelectorAll('.file-item').forEach(function(el, idx) {
        el.querySelector('.file-name').textContent = files[idx].name;
    });
    previewEl.style.display = 'block';
    if (btn) {
        btn.disabled = false;
        var label = files.length === 1 ? 'Przetwórz paragon' : 'Przetwórz ' + files.length + ' paragonów';
        btn.innerHTML = '<i class="bi bi-cpu me-1"></i> ' + label;
    }
}

async function handleBatchUpload(event) {
    event.preventDefault();
    var input = document.getElementById('file-input');
    var btn = document.getElementById('upload-btn');
    var resultDiv = document.getElementById('upload-result');
    var files = input.files;

    if (!files || files.length === 0) return;

    // Disable button
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Przetwarzanie...';
    resultDiv.innerHTML = '';

    // Show progress toast
    if (typeof showProgressToast === 'function') {
        showProgressToast('batch-upload', 'Przetwarzanie 0/' + files.length + ' paragonów...');
    }

    var successCount = 0;
    var errorCount = 0;

    for (var i = 0; i < files.length; i++) {
        var file = files[i];
        var fileItem = document.querySelector('.file-item[data-index="' + i + '"]');
        var statusBadge = fileItem ? fileItem.querySelector('.file-status') : null;

        // Mark as processing
        if (statusBadge) {
            statusBadge.className = 'badge bg-primary file-status';
            statusBadge.innerHTML = '<span class="spinner-border spinner-border-sm" style="width:.7rem;height:.7rem"></span>';
        }

        // Update progress toast
        if (typeof updateProgressToast === 'function') {
            updateProgressToast('batch-upload', 'Przetwarzanie ' + (i + 1) + '/' + files.length + ': ' + file.name);
        }

        try {
            var formData = new FormData();
            formData.append('file', file);

            var response = await fetch('/app/paragony/upload', {
                method: 'POST',
                body: formData
            });

            if (response.ok) {
                var html = await response.text();
                successCount++;
                if (statusBadge) {
                    statusBadge.className = 'badge bg-success file-status';
                    statusBadge.textContent = 'OK';
                }
                // Append result
                var wrapper = document.createElement('div');
                wrapper.className = 'mb-2';
                wrapper.innerHTML = html;
                resultDiv.appendChild(wrapper);
            } else {
                errorCount++;
                var errText = 'Błąd ' + response.status;
                try { errText = (await response.text()) || errText; } catch(e) {}
                if (statusBadge) {
                    statusBadge.className = 'badge bg-danger file-status';
                    statusBadge.textContent = 'Błąd';
                }
                var errDiv = document.createElement('div');
                errDiv.className = 'alert alert-danger py-1 px-2 small mb-2';
                errDiv.textContent = file.name + ': ' + errText;
                resultDiv.appendChild(errDiv);
            }
        } catch (err) {
            errorCount++;
            if (statusBadge) {
                statusBadge.className = 'badge bg-danger file-status';
                statusBadge.textContent = 'Błąd';
            }
            var errDiv = document.createElement('div');
            errDiv.className = 'alert alert-danger py-1 px-2 small mb-2';
            errDiv.textContent = file.name + ': ' + err.message;
            resultDiv.appendChild(errDiv);
        }
    }

    // Hide progress toast
    if (typeof hideProgressToast === 'function') {
        hideProgressToast('batch-upload');
    }

    // Summary
    var summaryClass = errorCount === 0 ? 'alert-success' : 'alert-warning';
    var summaryDiv = document.createElement('div');
    summaryDiv.className = 'alert ' + summaryClass + ' py-2 mt-2';
    summaryDiv.innerHTML = '<strong>Gotowe:</strong> ' + successCount + ' przetworzone' +
        (errorCount > 0 ? ', ' + errorCount + ' z błędami' : '');
    resultDiv.insertBefore(summaryDiv, resultDiv.firstChild);

    // Reset button
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-cpu me-1"></i> Przetwórz paragony';
}

/* Legacy single-file dropzone init (for backward compatibility) */
function initUploadDropzone(dropzoneId, inputId, previewId) {
    initBatchUpload(dropzoneId, inputId, previewId, 'upload-btn', 'upload-result');
}
