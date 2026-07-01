import os
import sys
import time
from retriever import Retriever

# Huggingface Hub / Streamlit Threading 버그(httpx client closed) 우회 및 오프라인 로드 강제
os.environ["HF_HUB_DISABLE_HTTP2"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["TQDM_DISABLE"] = "1"

try:
    from transformers.utils import logging as hf_logging
    hf_logging.disable_progress_bar()
except ImportError:
    pass

# Optional imports for LLM APIs
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    from google import genai
except ImportError:
    genai = None

class QnAAgent:
    def __init__(self):
        self.retrievers = {}
        self.model = None
        
        self.openai_api_key = os.environ.get("OPENAI_API_KEY")
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY")
        
        if not self.openai_api_key and not self.gemini_api_key:
            print("WARNING: Neither OPENAI_API_KEY nor GEMINI_API_KEY is set in environment.")
            print("Agent will only return retrieved context without LLM generation.")
            
        if self.openai_api_key and OpenAI:
            self.openai_client = OpenAI(api_key=self.openai_api_key)
        
        if self.gemini_api_key and genai:
            self.gemini_client = genai.Client(api_key=self.gemini_api_key)

    def get_retriever(self, chat_type: str):
        if chat_type not in self.retrievers:
            if self.model is None:
                from sentence_transformers import SentenceTransformer
                print("Loading shared embedding model...")
                # Streamlit의 멀티스레드 환경에서 httpx 세션 충돌을 방지하기 위해 재시도 로직 추가
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        self.model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
                        break
                    except Exception as e:
                        print(f"Model load attempt {attempt + 1} failed: {e}")
                        if attempt == max_retries - 1:
                            raise
                        time.sleep(1)
            
            brand = chat_type.replace("cs_", "").replace("qa_", "").replace("excel_", "")
            if brand == "store": brand = "thelittles" # Fallback
            if brand == "health": brand = "littlelabs" # Fallback
            
            db_path = f'data/vectors_{brand}.db'
            self.retrievers[chat_type] = Retriever(db_path=db_path, model=self.model)
        return self.retrievers[chat_type]

    def _build_prompt(self, query: str, contexts: list, chat_type: str = "health") -> str:
        context_str = "\n\n---\n\n".join([f"[검색된 지식]\n제목: {c.get('wr_subject', '')}\n내용:\n{c.get('chunk_text', '')}" for c in contexts])
        
        prompt = f"""아래에 제공된 [검색된 지식 DB 및 가이드 내용]을 최우선으로 참고하여 사용자의 질문에 답변을 작성해주세요.

[검색된 지식 DB 및 가이드 내용]
{context_str}

[사용자 질문]
{query}

답변:"""
        return prompt

    def _run_ocr(self, image_path: str) -> str:
        if not image_path or not os.path.exists(image_path):
            return ""
            
        print(f"Running OCR on image: {image_path}...")
        import base64
        try:
            with open(image_path, "rb") as image_file:
                b64_img = base64.b64encode(image_file.read()).decode('utf-8')
            
            ext = image_path.split('.')[-1].lower()
            mime_type = f"image/{ext}" if ext in ["png", "jpeg", "jpg", "gif", "webp"] else "image/jpeg"
            if ext == "jpg":
                mime_type = "image/jpeg"
                
            ocr_prompt = "이 이미지(제품 성분표, 패키지, 문의 캡처 등)에 있는 모든 텍스트를 정확하게 추출해서 한국어와 영어 텍스트 그대로 반환해주세요. 추가적인 설명이나 해석 없이, 오직 추출한 텍스트만 출력하세요."
            
            if self.openai_api_key and OpenAI:
                messages = [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": ocr_prompt},
                            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64_img}"}}
                        ]
                    }
                ]
                response = self.openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    temperature=0.1
                )
                ocr_text = response.choices[0].message.content.strip()
                print(f"OCR result length: {len(ocr_text)} chars")
                return ocr_text
        except Exception as e:
            print(f"Error during OCR preprocessing: {e}")
        return ""

    def generate_answer(self, query: str, top_k: int = 3, use_model: str = "openai", chat_type: str = "health", history: list = None, image_path: str = None) -> dict:
        ocr_text = ""
        search_query = query
        
        if image_path and os.path.exists(image_path):
            ocr_text = self._run_ocr(image_path)
            if ocr_text:
                # 검색 쿼리에 추출된 OCR 텍스트 결합 (최대 300자)
                search_query = f"{query} {ocr_text[:300]}"
                
        print(f"Searching for relevant past Q&A for: '{query}' (Search Query: '{search_query[:100]}...') ({chat_type})...")
        retriever = self.get_retriever(chat_type)
        contexts = retriever.hybrid_search(search_query, top_k=top_k)
        
        if not contexts:
            return {
                "answer": "관련된 과거 내역을 찾을 수 없습니다. 좀 더 구체적으로 질문해주세요.",
                "sources": []
            }
            
        prompt = self._build_prompt(query, contexts, chat_type)
        if ocr_text:
            prompt = f"[첨부 이미지에서 추출된 성분/텍스트 정보]\n{ocr_text}\n\n---\n\n" + prompt
            
        answer = ""
        
        system_content = "당신은 전문적이고 친절한 약사 '리틀약사'입니다." if chat_type == "health" else "당신은 전문적이고 친절한 '네이버 스토어 고객센터 매니저'입니다."
        
        try:
            import db
            custom_context = db.get_setting("custom_context", "")
            if custom_context:
                system_content += f"\n\n[추가 필수 지침(Context)]\n{custom_context}\n"
        except Exception:
            pass
            
        system_content += """
만약 사용자가 과거의 답변을 수정해달라고 하거나, 새로운 정보(질문과 답변 쌍)를 저장/기억해달라고 명시적으로 요청한다면,
당신의 일반적인 응답 내용 맨 마지막에 반드시 아래와 같은 정확한 형식으로 수정될 질문과 답변을 포함해주세요:
[UPDATE_QNA]
Q: (저장/수정할 질문)
A: (저장/수정된 답변)
[/UPDATE_QNA]
"""
        
        if use_model == "openai" and self.openai_api_key and OpenAI:
            api_messages = [{"role": "system", "content": system_content}]
            
            if history:
                # 최근 대화 내역 추가 (너무 길어지지 않게 최근 N개만 가져올 수도 있지만 전체를 넘깁니다)
                for msg in history[-10:]: # 최근 10개로 제한
                    role = msg.get("role", "user")
                    if role in ["user", "assistant"]:
                        api_messages.append({"role": role, "content": msg.get("content", "")})
            
            if image_path and os.path.exists(image_path):
                import base64
                with open(image_path, "rb") as image_file:
                    b64_img = base64.b64encode(image_file.read()).decode('utf-8')
                
                ext = image_path.split('.')[-1].lower()
                mime_type = f"image/{ext}" if ext in ["png", "jpeg", "jpg", "gif", "webp"] else "image/jpeg"
                if ext == "jpg":
                    mime_type = "image/jpeg"
                    
                api_messages.append({
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64_img}"}}
                    ]
                })
            else:
                api_messages.append({"role": "user", "content": prompt})
            
            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=api_messages,
                temperature=0.3
            )
            answer = response.choices[0].message.content
            
        elif use_model == "gemini" and self.gemini_api_key and genai:
            gemini_prompt = prompt
            if history:
                history_str = "\n".join([f"{msg.get('role', 'user')}: {msg.get('content', '')}" for msg in history[-10:]])
                gemini_prompt = f"[이전 대화 내역]\n{history_str}\n\n{prompt}"
                
            response = self.gemini_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=gemini_prompt,
                config={'temperature': 0.3}
            )
            answer = response.text
            
        else:
            answer = f"[LLM API 미설정 또는 라이브러리 누락]\n\n구성된 프롬프트:\n{prompt}"
            
        return {
            "answer": answer,
            "sources": [{"subject": c.get('wr_subject', ''), "type": c.get('chunk_type', ''), "date": c.get('wr_datetime', '')} for c in contexts]
        }

    def update_knowledge_base(self, chat_type: str, question: str, answer: str):
        import sqlite3
        import uuid
        import struct
        from datetime import datetime

        if self.model is None:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
            
        chunk_text = f"[사용자요청수정]\n[질문] {question}\n[답변] {answer}"
        emb = self.model.encode(chunk_text, normalize_embeddings=True).tolist()
        emb_bytes = struct.pack(f'{len(emb)}f', *emb)
        
        brand = chat_type.replace("cs_", "").replace("qa_", "").replace("excel_", "")
        if brand == "store": brand = "thelittles"
        if brand == "health": brand = "littlelabs"
        
        db_path = f'data/vectors_{brand}.db'
        
        # Ensure DB is initialized
        import naver_api_agent
        naver_api_agent.init_vector_db(db_path, self.model.get_sentence_embedding_dimension())
        
        q_id = f"manual_{uuid.uuid4().hex[:8]}"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO chunks (inquiry_id, chunk_text, product_name, subject, is_answered, embedding)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (q_id, chunk_text, '수정된지식', question, 1, emb_bytes))
        conn.commit()
        conn.close()
        print(f"[{brand.upper()} DB UPDATED] {question}")

    def delete_knowledge(self, chat_type: str, chunk_id: int):
        import sqlite3
        
        brand = chat_type.replace("cs_", "").replace("qa_", "").replace("excel_", "")
        if brand == "store": brand = "thelittles"
        if brand == "health": brand = "littlelabs"
        
        db_path = f'data/vectors_{brand}.db'
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM chunks WHERE id = ?", (chunk_id,))
        conn.commit()
        conn.close()
        print(f"[{brand.upper()} DB DELETED] Chunk ID: {chunk_id}")

    def edit_knowledge(self, chat_type: str, chunk_id: int, new_subject: str, new_chunk_text: str):
        import sqlite3
        import struct
        
        if self.model is None:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
            
        emb = self.model.encode(new_chunk_text, normalize_embeddings=True).tolist()
        emb_bytes = struct.pack(f'{len(emb)}f', *emb)
        
        brand = chat_type.replace("cs_", "").replace("qa_", "").replace("excel_", "")
        if brand == "store": brand = "thelittles"
        if brand == "health": brand = "littlelabs"
        
        db_path = f'data/vectors_{brand}.db'
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE chunks 
            SET subject = ?, chunk_text = ?, embedding = ?
            WHERE id = ?
        ''', (new_subject, new_chunk_text, emb_bytes, chunk_id))
        conn.commit()
        conn.close()
        print(f"[{brand.upper()} DB EDITED] Chunk ID: {chunk_id}")

if __name__ == "__main__":
    agent = QnAAgent()
    
    print("\n" + "="*50)
    print("리틀약사 AI 답변 에이전트 CLI 프로토타입")
    print("종료하려면 'exit' 또는 'quit'을 입력하세요.")
    print("="*50 + "\n")
    
    # 선호하는 모델 선택 (openai 또는 gemini)
    preferred_model = "openai" if os.environ.get("OPENAI_API_KEY") else "gemini"
    
    while True:
        try:
            query = input("\nQ: ")
            if query.lower() in ['exit', 'quit']:
                break
            if not query.strip():
                continue
                
            result = agent.generate_answer(query, use_model=preferred_model)
            
            print(f"\nA: {result['answer']}")
            print("\n[참고한 과거 상담]")
            for i, src in enumerate(result['sources'], 1):
                print(f"  {i}. {src['subject']} ({src['date']})")
                
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"\n오류 발생: {e}")
