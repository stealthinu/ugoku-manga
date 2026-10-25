# Third-party notices

This project downloads model weights at run time. None are bundled in this repository.
Check each licence yourself before use. The authoritative list is `ugoku/models.py`.

| model | role | licence | note |
|---|---|---|---|
| comic-text-detector (ONNX conversion) | text pixel segmentation | GPL-3.0 upstream (hosting page says Apache-2.0) | optional user download; treat as GPL-3.0. Isolated behind `ugoku/pipeline/detect/text.py` |
| comic-text-and-bubble-detector (RT-DETR) | bubble and text boxes | Apache-2.0 | optional user download |
| lama-manga (LaMa fine-tuned on manga/anime) | inpainting | Apache-2.0 / MIT | optional user download; the dynamic-shape export is supplied by the user (see `ugoku/models.py`) |

Video generation models (e.g. MiniMax H3) are not distributed here. Their own licence terms apply to you.
