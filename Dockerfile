FROM python:3.12-slim

WORKDIR /app

# 시스템 패키지 (sentence-transformers / torch 런타임에 필요)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

# 의존성 먼저 설치 (레이어 캐시 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 임베딩 모델을 빌드 단계에서 미리 다운로드해 이미지에 포함
# (컨테이너 재생성 시 매번 재다운로드 방지 + 오프라인 구동 가능)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')"

# 애플리케이션 코드 복사
COPY . .

EXPOSE 8501

# Streamlit 헬스체크
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
