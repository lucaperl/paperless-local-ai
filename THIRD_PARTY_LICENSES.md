# Third-party licenses

`paperless-local-ai` source code in this repository is licensed under the MIT License. That license does **not** replace the licenses of the software installed into or used by the container images.

In particular, the OCR runtime directly uses **PyMuPDF**. PyMuPDF's upstream project states that it is available under the **GNU Affero General Public License v3 (AGPL-3.0)** for open-source use, with separate commercial licensing available from Artifex. Anyone redistributing or operating a build that includes PyMuPDF must comply with the applicable PyMuPDF/MuPDF license terms.

The OCR runtime also uses PaddlePaddle/PaddleOCR/PaddleX and other Python packages under their respective upstream licenses. The installed Python distributions and base images carry their own license metadata/notices where provided by the upstream packages.

This file is a dependency notice, not legal advice. Always review the exact licenses of the versions you redistribute, especially when making a modified image or using the software in a proprietary/commercial product.
