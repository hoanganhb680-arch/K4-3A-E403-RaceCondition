from __future__ import annotations

from app.database import reset_db
from app.services.pipeline import add_message, add_transcript, create_session, process_session


SESSION_ID = "ai-fundamentals"

CHAT_STREAM = [
    ("minh", "Minh", "student", "LLM có nhớ toàn bộ hội thoại không?"),
    ("teacher", "Giảng viên", "teacher", "LLM không nhớ toàn bộ, chỉ xử lý trong context window hiện tại và phần lịch sử được đưa vào prompt."),
    ("lan", "Lan", "student", "Context window là bao nhiêu token vậy?"),
    ("huy", "Huy", "student", "RAG có cần fine-tuning không?"),
    ("phuong", "Phương", "student", "Temperature, top-k và top-p khác nhau như thế nào?"),
    ("nam", "Nam", "student", "Có cách nào giảm chi phí khi dùng OpenAI API không?"),
    ("quan", "Quân", "student", "Có cách nào tối ưu chi phí API không?"),
    ("ha", "Hà", "student", "Có cách nào ưu tiên model rẻ hơn mà vẫn đảm bảo chất lượng không?"),
    ("mai", "Mai", "student", "Prompt engineering có tài liệu nào hay không ạ?"),
    ("anh", "Anh", "student", "Có nguồn nào học prompt engineering tốt không?"),
    ("khoa", "Khoa", "student", "Function calling hoạt động thế nào?"),
    ("trang", "Trang", "student", "Token limit vượt thì sao ạ?"),
    ("dat", "Đạt", "student", "Model GPT-4o và Gemini 1.5 khác gì nhau về khả năng suy luận?"),
    ("quan", "Quân", "student", "Trong RAG có cần xây dựng vector database riêng không?"),
    ("linh", "Linh", "student", "Có thể fine-tune LLM trên dữ liệu tiếng Việt không?"),
]

TRANSCRIPT = """
00:05:12 Giảng viên: Hôm nay chúng ta tìm hiểu Large Language Models trong lớp AI Fundamentals.
LLM không tự nhớ toàn bộ mọi thứ, nó chỉ dùng phần context window được truyền vào khi suy luận.

00:18:47 Giảng viên: Temperature điều khiển độ ngẫu nhiên. Top-k giới hạn số lựa chọn token tốt nhất,
còn top-p chọn nhóm token theo xác suất tích luỹ. Ba tham số này ảnh hưởng đến độ đa dạng của câu trả lời.

00:32:10 Giảng viên: Với RAG, không phải lúc nào cũng cần fine-tuning. RAG phù hợp khi muốn đưa tài liệu
mới vào hệ thống mà không huấn luyện lại mô hình. Fine-tuning chỉ nên dùng khi cần thay đổi hành vi ổn định.

00:41:30 Giảng viên: Function calling nghĩa là mô hình trả về lời gọi hàm có cấu trúc, ví dụ tên hàm và arguments.
Backend nhận cấu trúc đó, gọi tool thật, rồi đưa kết quả trở lại cho mô hình hoặc giao diện.
"""


def seed_demo() -> None:
    reset_db()
    create_session("AI Fundamentals - LLM", SESSION_ID)
    for user_id, display_name, role, content in CHAT_STREAM:
        add_message(SESSION_ID, user_id, content, display_name, role)
    add_transcript(SESSION_ID, "zoom_live_transcript", TRANSCRIPT)
    process_session(SESSION_ID, top_k=5)


def main() -> None:
    seed_demo()
    print(f"Seeded workflow demo session: {SESSION_ID}")


if __name__ == "__main__":
    main()
