# Third-party licenses

`paperless-local-ai` source code in this repository is licensed under the MIT License. That license does **not** replace the licenses of software installed into or used by the container images.

The OCR image directly uses PaddlePaddle, PaddleOCR and PaddleX; PaddleOCR/PaddleX also require `requests`, which is explicitly pinned in the OCR image. The HPI CPU installation also brings in optimized inference/tooling dependencies selected by PaddleX, including OpenVINO/ONNX-related components. These projects and their transitive dependencies retain their respective upstream licenses and notices.

The core image directly uses `requests` and **scikit-learn**. scikit-learn brings its scientific-Python runtime dependencies, including NumPy, SciPy, joblib and threadpoolctl. These packages retain their respective upstream licenses and notices.

Base images and installed Python distributions retain their own license metadata/notices where provided upstream.

This file is a dependency notice, not legal advice. Review the licenses of the exact versions you redistribute, especially for modified images or proprietary/commercial deployments.
