import sqlite3
import struct
from sentence_transformers import SentenceTransformer
import numpy as np

class Retriever:
    def __init__(self, db_path: str = 'data/counseling_vectors.db', model_name: str = 'paraphrase-multilingual-MiniLM-L12-v2', model=None):
        self.db_path = db_path
        if model:
            self.model = model
        else:
            print(f"Loading embedding model ({model_name})...")
            self.model = SentenceTransformer(model_name)
        
        # 임베딩 차원 확인
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT value FROM metadata WHERE key='embedding_dim'")
            row = cursor.fetchone()
            self.dim = int(row[0]) if row else 384
        except sqlite3.OperationalError:
            self.dim = 384
        conn.close()
        print(f"Retriever initialized for {self.db_path}.")

    def _bytes_to_embedding(self, data: bytes) -> list:
        return list(struct.unpack(f'{self.dim}f', data))

    def _cosine_similarity(self, a: list, b: list) -> float:
        a = np.array(a)
        b = np.array(b)
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))

    def search_similar(self, query: str, top_k: int = 5, min_similarity: float = 0.3) -> list:
        query_emb = self.model.encode(query, normalize_embeddings=True).tolist()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        is_naver = "naver" in self.db_path
        rows = []
        try:
            if is_naver:
                cursor.execute("SELECT id, inquiry_id, chunk_text, product_name, subject, is_answered, embedding FROM chunks")
            else:
                cursor.execute(
                    "SELECT id, wr_id, chunk_type, chunk_text, ca_name, wr_subject, wr_datetime, wr_qna_ok, embedding "
                    "FROM chunks"
                )
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            pass
        
        results = []
        for row in rows:
            if is_naver:
                emb = self._bytes_to_embedding(row[6])
                sim = self._cosine_similarity(query_emb, emb)
                if sim >= min_similarity:
                    results.append((sim, {
                        'id': row[0],
                        'wr_id': row[1],
                        'chunk_type': '스토어문의',
                        'chunk_text': row[2],
                        'ca_name': '네이버스토어',
                        'wr_subject': row[4] if row[4] else row[3], # subject or product_name
                        'wr_datetime': '',
                        'wr_qna_ok': row[5],
                    }))
            else:
                emb = self._bytes_to_embedding(row[8])
                sim = self._cosine_similarity(query_emb, emb)
                if sim >= min_similarity:
                    results.append((sim, {
                        'id': row[0],
                        'wr_id': row[1],
                        'chunk_type': row[2],
                        'chunk_text': row[3],
                        'ca_name': row[4],
                        'wr_subject': row[5],
                        'wr_datetime': row[6],
                        'wr_qna_ok': row[7],
                    }))
        
        results.sort(key=lambda x: x[0], reverse=True)
        conn.close()
        return results[:top_k]
        
        results.sort(key=lambda x: x[0], reverse=True)
        conn.close()
        return results[:top_k]

    def search_fts(self, query: str, top_k: int = 5) -> list:
        is_naver = "naver" in self.db_path
        if is_naver:
            # Naver DB does not have FTS yet, so return empty for hybrid_search to just use vector
            return []
            
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # sqlite fts5 match syntax
        fts_query = " OR ".join([f'"{word}"' for word in query.split()])
        
        rows = []
        try:
            cursor.execute('''
                SELECT c.id, c.wr_id, c.chunk_type, c.chunk_text, c.ca_name, 
                       c.wr_subject, c.wr_datetime, c.wr_qna_ok, 
                       chunks_fts.rank
                FROM chunks_fts
                JOIN chunks c ON chunks_fts.rowid = c.id
                WHERE chunks_fts MATCH ?
                ORDER BY chunks_fts.rank
                LIMIT ?
            ''', (fts_query, top_k))
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            try:
                # Fallback for simple query if syntax error
                cursor.execute('''
                    SELECT c.id, c.wr_id, c.chunk_type, c.chunk_text, c.ca_name, 
                           c.wr_subject, c.wr_datetime, c.wr_qna_ok, 
                           chunks_fts.rank
                    FROM chunks_fts
                    JOIN chunks c ON chunks_fts.rowid = c.id
                    WHERE chunks_fts MATCH ?
                    ORDER BY chunks_fts.rank
                    LIMIT ?
                ''', (query, top_k))
                rows = cursor.fetchall()
            except sqlite3.OperationalError:
                pass

        results = []
        for row in rows:
            results.append({
                'id': row[0],
                'wr_id': row[1],
                'chunk_type': row[2],
                'chunk_text': row[3],
                'ca_name': row[4],
                'wr_subject': row[5],
                'wr_datetime': row[6],
                'wr_qna_ok': row[7],
                'fts_rank': row[8],
            })
        
        conn.close()
        return results

    def hybrid_search(self, query: str, top_k: int = 3, vector_weight: float = 0.7, fts_weight: float = 0.3) -> list:
        vector_results = self.search_similar(query, top_k=top_k * 2)
        fts_results = self.search_fts(query, top_k=top_k * 2)
        
        scores = {}
        
        for rank, (sim, chunk) in enumerate(vector_results):
            chunk_id = chunk['id']
            if chunk_id not in scores:
                scores[chunk_id] = {'chunk': chunk, 'score': 0}
            scores[chunk_id]['score'] += vector_weight * (1.0 / (rank + 1))
        
        for rank, chunk in enumerate(fts_results):
            chunk_id = chunk['id']
            if chunk_id not in scores:
                scores[chunk_id] = {'chunk': chunk, 'score': 0}
            scores[chunk_id]['score'] += fts_weight * (1.0 / (rank + 1))
        
        ranked = sorted(scores.values(), key=lambda x: x['score'], reverse=True)
        return [item['chunk'] for item in ranked[:top_k]]

if __name__ == "__main__":
    retriever = Retriever()
    res = retriever.hybrid_search("유산균 추천")
    for r in res:
        print(f"[{r['chunk_type']}] {r['wr_subject']}")
