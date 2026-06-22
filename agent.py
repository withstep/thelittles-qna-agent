import os
import sys
from retriever import Retriever

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
                self.model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
            
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

    def generate_answer(self, query: str, top_k: int = 3, use_model: str = "openai", chat_type: str = "health") -> dict:
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
        
        if use_model == "openai" and self.openai_api_key and OpenAI:
            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3
            )
            answer = response.choices[0].message.content
            
        elif use_model == "gemini" and self.gemini_api_key and genai:
            response = self.gemini_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config={'temperature': 0.3}
            )
            answer = response.text
            
        else:
            answer = f"[LLM API 미설정 또는 라이브러리 누락]\n\n구성된 프롬프트:\n{prompt}"
            
        return {
            "answer": answer,
            "sources": [{"subject": c.get('wr_subject', ''), "type": c.get('chunk_type', ''), "date": c.get('wr_datetime', '')} for c in contexts]
        }

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
