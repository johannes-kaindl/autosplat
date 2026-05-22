// the PlayCanvas SOG loader cannot read blob: URLs, so user uploads
// are limited to .ply; the bundled demo splat is SOG (served over http)
const ACCEPT = /\.ply$/i;

export function initDropzone({ stage, hint, fileInput, openButton, onFile }) {
  function handleFile(file) {
    if (file && ACCEPT.test(file.name)) onFile(file);
    else onFile(null, file ? file.name : '');
  }

  ['dragenter', 'dragover'].forEach(ev =>
    stage.addEventListener(ev, (e) => {
      e.preventDefault();
      hint.hidden = false;
    }));

  ['dragleave', 'drop'].forEach(ev =>
    stage.addEventListener(ev, (e) => {
      e.preventDefault();
      if (ev === 'dragleave' && stage.contains(e.relatedTarget)) return;
      hint.hidden = true;
    }));

  stage.addEventListener('drop', (e) => {
    const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    handleFile(file);
  });

  openButton.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', () => {
    handleFile(fileInput.files[0]);
    fileInput.value = '';
  });
}
