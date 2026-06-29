import os
import sys
import time
from retriever import Retriever

# Huggingface Hub / Streamlit Threading 버그(httpx client closed) 우회 및 오프라인 로드 강제
os.environ["HF_HUB_DISABLE_HTTP2"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["HF_HUB_OFFLINE"] = "1"

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
            
            if chat_type == "store":
                self.retrievers[chat_type] = Retriever(db_path='naver_data/naver_vectors.db', model=self.model)
            else:
                self.retrievers[chat_type] = Retriever(db_path='data/counseling_vectors.db', model=self.model)
        return self.retrievers[chat_type]

    def _build_prompt(self, query: str, contexts: list, chat_type: str = "health") -> str:
        context_str = "\n\n---\n\n".join([f"[과거 내역]\n제목: {c.get('wr_subject', '')}\n내용:\n{c.get('chunk_text', '')}" for c in contexts])
        
        if chat_type == "store":
            prompt = f"""당신은 '네이버 스토어 고객센터 매니저'라는 이름의 친절하고 전문적인 상담원입니다.
사용자의 스토어 및 제품 관련 문의에 대해 답변해주세요.

아래에 제공된 [과거 내역]은 제품 정보, 배송, 교환/반품 등과 관련된 데이터입니다.
이 정보들을 최우선으로 참고하여 정확하고 친절하게 답변을 제공하세요.
답변은 "~해요", "~합니다" 등의 고객 서비스에 적합한 부드러운 말투를 사용하세요.

[과거 내역]
{context_str}

[사용자 질문]
{query}

답변:"""
        else:
            prompt = f"""당신은 '리틀약사'라는 이름의 친절하고 전문적인 약사입니다.
사용자의 건강 관련 질문이나 영양제 추천 요청에 대해 답변해주세요.

아래에 제공된 [과거 내역]은 당신이 이전에 다른 환자/고객들에게 답변했던 내용입니다.
이 정보들을 최우선으로 참고하여 일관성 있는 답변을 제공하세요.
만약 과거 상담 내역에 충분한 정보가 없다면, 일반적인 약학적 지식을 바탕으로 안전하게 조언하되, 직접적인 의학적 진단은 피하세요.
답변은 "~해요", "~합니다" 등의 부드럽고 친절한 말투를 사용하세요.

[과거 내역]
{context_str}

[사용자 질문]
{query}

답변:"""
        return prompt

    def generate_answer(self, query: str, top_k: int = 3, use_model: str = "openai", chat_type: str = "health", history: list = None) -> dict:
        print(f"Searching for relevant past Q&A for: '{query}' ({chat_type})...")
        retriever = self.get_retriever(chat_type)
        contexts = retriever.hybrid_search(query, top_k=top_k)
        
        if not contexts:
            return {
                "answer": "관련된 과거 내역을 찾을 수 없습니다. 좀 더 구체적으로 질문해주세요.",
                "sources": []
            }
            
        prompt = self._build_prompt(query, contexts, chat_type)
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
        
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if chat_type == "store":
            db_path = 'naver_data/naver_vectors.db'
            q_id = f"manual_{uuid.uuid4().hex[:8]}"
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO chunks (inquiry_id, chunk_text, product_name, subject, is_answered, embedding)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (q_id, chunk_text, '수정된지식', question, 1, emb_bytes))
            conn.commit()
            conn.close()
            print(f"[STORE DB UPDATED] {question}")
        else:
            db_path = 'data/counseling_vectors.db'
            wr_id = f"manual_{uuid.uuid4().hex[:8]}"
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO chunks (wr_id, chunk_type, chunk_text, ca_name, wr_subject, wr_datetime, wr_qna_ok, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (wr_id, 'manual', chunk_text, '사용자입력', question, now_str, '1', emb_bytes))
            conn.commit()
            conn.close()
            print(f"[HEALTH DB UPDATED] {question}")
            
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
