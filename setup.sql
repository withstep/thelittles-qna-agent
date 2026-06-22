-- =====================================================================
-- Synology MariaDB 초기 설정 SQL
-- phpMyAdmin 또는 `mysql -u root -p -P 3307` 로 접속 후 실행
-- =====================================================================

-- 1. 데이터베이스 생성 (utf8mb4: 한글/이모지 안전)
CREATE DATABASE IF NOT EXISTS littlelabs_qna_agent
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 2. Docker 컨테이너에서 TCP로 접속할 수 있도록 권한 부여
--    Synology MariaDB의 root는 보통 localhost 전용이라,
--    컨테이너(다른 IP)에서 붙으려면 별도 호스트 권한이 필요하다.
--    아래는 사설망 전체(172.x, 192.168.x)에서의 접속을 허용하는 예시.
--    보안을 위해 root 대신 전용 계정 사용을 권장.
GRANT ALL PRIVILEGES ON littlelabs_qna_agent.* TO 'root'@'172.%';
GRANT ALL PRIVILEGES ON littlelabs_qna_agent.* TO 'root'@'192.168.%';
FLUSH PRIVILEGES;

-- (선택) 전용 계정을 쓰려면 위 root 라인 대신 아래 사용 후
--        .env 의 DB_USER / DB_PASSWORD 를 맞춰준다.
-- CREATE USER IF NOT EXISTS 'qna_app'@'172.%' IDENTIFIED BY '강력한비밀번호';
-- CREATE USER IF NOT EXISTS 'qna_app'@'192.168.%' IDENTIFIED BY '강력한비밀번호';
-- GRANT ALL PRIVILEGES ON littlelabs_qna_agent.* TO 'qna_app'@'172.%';
-- GRANT ALL PRIVILEGES ON littlelabs_qna_agent.* TO 'qna_app'@'192.168.%';
-- FLUSH PRIVILEGES;

-- 테이블(chats, messages)은 앱이 시작될 때 db.init_db() 가 자동 생성한다.
