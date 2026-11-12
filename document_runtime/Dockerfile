FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS runtime-base
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer poppler-utils fonts-liberation fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir python-docx==1.2.0 pypdf==7.0.0 pdfplumber==0.11.10
FROM runtime-base
COPY document_inspection.py gost_formatter.py document_layout.py document_elements.py metafile_layout.py standard_profiles.py /opt/butuz/
COPY standards/gost_r_2_105_2019.json standards/gost_r_2_104_2023.json /opt/butuz/standards/
COPY standards/profiles/eskd_text.json /opt/butuz/standards/profiles/
COPY document_runtime/worker.py /opt/butuz/worker.py
USER 65534:65534
WORKDIR /work
ENTRYPOINT ["python", "-I", "/opt/butuz/worker.py"]
