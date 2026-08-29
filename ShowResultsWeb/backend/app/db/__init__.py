"""權重登錄簿的資料庫層。

這是本專案第一次引入資料庫，而 `docs/architecture.md` §2 原本明列「無資料庫」是刻意
設計。那個決策仍然成立於**session 狀態**——載入了哪些模型、目前選了哪個裝置，這些
是執行期狀態，重啟後本來就該重來。

資料庫解決的是另一件事：`session_id` 每次掃描都重新產生，LocalLibrary 來源的 session
依設計不落地，所以「這顆權重我測過、超參數是什麼、當時實測 mAP 多少」在重啟後全部消失。
登錄簿是**長期帳本**，身分用權重檔內容的 SHA-256，與 session 的生命週期完全脫鉤。

雙軌：`DATABASE_URL` 未設定時走 SQLite 檔案（本機開發、CI、pytest 全部零設定），
docker-compose.yml 注入 PostgreSQL 連線字串。因此模型定義只用 SQLAlchemy 的通用型別
（`JSON` / `Float` / `String`），**不得使用 `JSONB`、`ARRAY` 等 Postgres 專屬型別**，
否則雙軌立刻失效。
"""
