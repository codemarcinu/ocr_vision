/* Second Brain - File Upload Handler */

function initUploadDropzone(dropzoneId, inputId, previewId) {
    var dropzone = document.getElementById(dropzoneId);
    var input = document.getElementById(inputId);
    var preview = document.getElementById(previewId);
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
            showPreview(files[0], preview);
        }
    });

    input.addEventListener('change', function() {
        if (input.files.length > 0) {
            showPreview(input.files[0], preview);
        }
    });

    function showPreview(file, previewEl) {
        if (!previewEl) return;
        var icon = file.type === 'application/pdf' ? '📄' : '🖼️';
        var size = (file.size / 1024).toFixed(1);
        previewEl.innerHTML =
            '<div class="d-flex align-items-center gap-2 mt-3">' +
            '<span class="fs-3">' + icon + '</span>' +
            '<div>' +
            '<div class="fw-medium">' + file.name + '</div>' +
            '<div class="text-muted small">' + size + ' KB</div>' +
            '</div></div>';
        previewEl.style.display = 'block';
    }
}
