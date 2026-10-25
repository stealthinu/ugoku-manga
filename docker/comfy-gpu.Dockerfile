# GPU worker image for the comfy_h3 backend: ComfyUI plus the job script. The model weights (MiniMax H3) are NOT included; mount them and
# point extra_model_paths.yaml at them. Check the H3 licence terms before use. Run it through the `local` runner or as the target of an external runner.
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip git ffmpeg libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
ARG COMFYUI_REF=master
RUN git clone https://github.com/comfyanonymous/ComfyUI /opt/ComfyUI && cd /opt/ComfyUI && git checkout ${COMFYUI_REF} && pip3 install --no-cache-dir -r requirements.txt
RUN pip3 install --no-cache-dir av requests pillow numpy
WORKDIR /job
COPY ugoku/gpu_scripts/comfy_h3_job.py /job/comfy_h3_job.py
ENV UGOKU_COMFY_DIR=/opt/ComfyUI UGOKU_COMFY_EXTRA=/models/extra_model_paths.yaml UGOKU_COMFY_DATA=/job/comfy-data
VOLUME ["/models", "/job/work"]
ENTRYPOINT ["python3", "/job/comfy_h3_job.py"]
CMD ["--root", "/job/work"]
