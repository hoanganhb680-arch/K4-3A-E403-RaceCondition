# AI SPEC - Tổng hợp câu hỏi chưa được trả lời sau buổi học · Nhóm RaceCondition · Zone E403
Hướng: [x] A - VLearn  [ ] B - Trợ lý Học viên  [ ] C - Làn mở
Loại: [x] Tối ưu tính năng có sẵn  [ ] Tính năng mới

## §1. User & Job
- Job executor + workflow: Giảng viên dạy lớp online trên VLearn Live. Trong lúc dạy, chat lớp có nhiều câu hỏi lặp ý, một số câu đã được trả lời trong chat hoặc transcript, một số câu bị trôi. Sau buổi học, giảng viên cần xem nhanh danh sách câu hỏi còn tồn đọng để trả lời bổ sung hoặc gửi recap.
- Core JTBD: Khi kết thúc một buổi học có nhiều chat, giảng viên muốn biết những nhóm câu hỏi nào học viên hỏi nhiều mà chưa được trả lời rõ, để xử lý sau buổi học mà không phải đọc lại toàn bộ chat và transcript.
- Problem statement: Giảng viên bị mất thời gian rà lại chat và transcript sau buổi học, dễ bỏ sót các câu hỏi quan trọng hoặc nhầm các câu hỏi đã được trả lời là vẫn còn tồn đọng.
- Evidence:
  - Dữ liệu prototype lấy từ `backend/data/golden_set.json`, flow seed demo và importer VLearn pack trong `backend/app/services/vlearn_importer.py`.
  - Golden set hiện có 21 case: 5 phát hiện câu hỏi, 6 gom câu hỏi trùng ý, 10 kiểm tra câu hỏi đã được trả lời chưa.
  - Ví dụ câu hỏi học viên: "LLM có nhớ toàn bộ hội thoại không?"
  - Ví dụ câu hỏi học viên: "Context window là bao nhiêu token vậy?"
  - Ví dụ câu hỏi học viên: "RAG có cần fine-tuning không?"
  - Ví dụ câu hỏi học viên: "Có cách nào giảm chi phí khi dùng OpenAI API không?"
  - Ví dụ câu hỏi học viên: "Prompt engineering có tài liệu nào hay không ạ?"
  - Ví dụ câu hỏi học viên: "Token limit vượt thì sao ạ?"

## §2. Impact & Quyết Định Chọn
| Ứng viên | Ai dùng | Tần suất | Tốn gì mỗi lần nếu làm tay | Khả thi prototype | Quyết định |
|---|---:|---:|---|---|---|
| Tổng hợp nhóm câu hỏi chưa được trả lời | Giảng viên | Sau mỗi buổi học | 20-40 phút đọc chat, transcript, tự gom câu giống nhau | Cao, đã có chat, transcript, SQLite, dashboard | Chọn |
| Chatbot trả lời ngay cho học viên | Học viên | Trong buổi học | Giảm một số câu hỏi lặp nhưng dễ trả lời sai khi thiếu ngữ cảnh | Trung bình, cần kiểm soát hallucination mạnh hơn | Loại |
| Tự động gửi email recap cho cả lớp | Giảng viên và học viên | Sau mỗi buổi học | Tiết kiệm thao tác gửi nhưng rủi ro gửi nội dung sai | Trung bình, cần HITL và quyền gửi mail | Loại |

- Ứng viên đã loại:
  - Chatbot trả lời ngay cho học viên: cost-of-error cao hơn vì câu trả lời sai xuất hiện trực tiếp trong lớp.
  - Tự động gửi email recap: chưa cần ở CP3 vì rủi ro gửi sai lớn hơn lợi ích tự động hóa.
- Ứng viên chọn:
  - Dashboard tổng hợp Top-K nhóm câu hỏi chưa được trả lời. Lý do: tác động trực tiếp tới việc sau buổi học, rủi ro thấp hơn vì giảng viên vẫn xem lại trước khi dùng.

## §3. Giải Pháp Tương Tự Đã Nghiên Cứu
| Giải pháp tương tự | Flow đáng học | Điểm cần né | Mình khác gì |
|---|---|---|---|
| Tìm kiếm trong transcript Zoom/Teams | Có transcript theo thời gian để truy vết lại nội dung đã nói | Chỉ search keyword, không gom các câu hỏi cùng ý | Gom câu hỏi theo ngữ nghĩa và đối chiếu chat + transcript |
| LMS/forum Q&A thủ công | Giảng viên có thể xem từng câu hỏi | Dễ trôi câu hỏi trong chat live, không biết câu nào đã được trả lời miệng | Chấm trạng thái ANSWERED/PARTIALLY_ANSWERED/UNANSWERED |
| Công cụ summary cuộc họp | Tóm tắt nhanh nội dung buổi học | Summary chung không tối ưu cho câu hỏi chưa xử lý | Tập trung vào danh sách hành động cho giảng viên sau buổi học |

## §4. Thiết Kế
- Lát cắt một câu: Giảng viên chọn một meeting đã diễn ra, hệ thống gom các câu hỏi học viên hỏi giống nhau, kiểm tra bằng chat và transcript xem câu nào đã được trả lời, rồi lưu Top-K nhóm câu hỏi cần xử lý sau buổi học.
- Non-goals:
  - Không tự gửi email thật cho học viên.
  - Không thay giảng viên trả lời câu hỏi trong lớp live.
  - Không build hệ thống phân quyền đầy đủ.
  - Không tối ưu cho hàng triệu bản ghi hoặc nhiều tenant.
- Mức prototype: [x] Working.
  - Thật: backend FastAPI, SQLite, import chat/transcript, embedding local hoặc Gemini, gom câu hỏi, dashboard Next.js, lưu summary.
  - Mock/giới hạn: dữ liệu VLearn pack local, tài khoản giảng viên cố định, chưa có auth.
- Automation: [x] augment  [x] conditional  [ ] automate.
  - Hệ thống tự gom và đề xuất, nhưng giảng viên vẫn xem danh sách trước khi dùng. Tự động hóa hoàn toàn bị hoãn vì gửi sai câu hỏi hoặc bỏ sót câu hỏi quan trọng sẽ ảnh hưởng trải nghiệm lớp.

### §4b. Nguyên Tắc Đã Áp Dụng
| Nguyên tắc | Áp cụ thể vào prototype |
|---|---|
| Human control | Giảng viên bấm "Tổng hợp câu hỏi" và xem trước kết quả, không auto-send |
| Show useful evidence | Dashboard cho xem câu hỏi gốc, số lượt hỏi, người hỏi, trạng thái đã trả lời |
| Graceful fallback | Nếu không có Gemini API key hoặc model lỗi, backend dùng local fallback |
| Set expectations | UI hiển thị thời gian xử lý, trạng thái lỗi khi không kết nối backend hoặc API |
| Reviewability | Mỗi summary được lưu vào SQLite theo `session_id`, có tab xem lại lịch sử |

## §5. Kiểu Lỗi - 4 Lớp Chỗ Khó Và Kịch Bản
| Lớp lỗi | Kịch bản | Tác hại | Cách xử lý hiện tại |
|---|---|---|---|
| Input/data | Chat thiếu tên học viên hoặc role sai | Sai số người hỏi, sai nhóm student/assistant | Chuẩn hóa role, fallback display name bằng user id |
| Input/data | Transcript thiếu đoạn giảng viên đã trả lời | Câu đã trả lời bị đánh dấu chưa trả lời | Cho status PARTIALLY_ANSWERED/UNANSWERED và giữ human review |
| Input/data | Câu hỏi không có dấu hỏi | Bỏ sót câu hỏi thật | Bộ detect dùng marker tiếng Việt và model classifier khi có key |
| Dedup | Hai câu hỏi cùng ý nhưng dùng từ khác nhau | Bị tách thành nhiều nhóm | Embedding + synonym normalization + cosine similarity |
| Dedup | Hai câu hỏi có từ giống nhau nhưng ý khác | Gom nhầm | Có conflict rules cho một số cặp dễ nhầm |
| Answer classification | Context liên quan nhưng chưa trả lời đủ | Đánh dấu ANSWERED quá sớm | Có trạng thái PARTIALLY_ANSWERED |
| Answer classification | Model trả JSON lỗi hoặc timeout | Pipeline fail | Catch exception và fallback local |
| UI/ops | Backend chưa chạy | Frontend không lấy được dữ liệu | UI báo lỗi khi summarize hoặc fetch fail |
| UI/ops | Summary chạy lâu | Giảng viên tưởng app treo | UI có elapsed time và loading state |
| Domain | Câu hỏi cần kiến thức ngoài transcript | Hệ thống không có bằng chứng trả lời | Chỉ đánh giá dựa trên evidence hiện có, không tự bịa câu trả lời |

## §6. Bốn Đường Đi Của Trải Nghiệm
- Happy path: Giảng viên mở lịch, chọn meeting đã diễn ra, bấm "Tổng hợp câu hỏi", xem Top-K nhóm câu hỏi, mở từng nhóm để xem câu hỏi gốc, summary được lưu vào SQLite.
- Low-confidence: Nếu bằng chứng chỉ liên quan một phần, câu hỏi được giữ ở PARTIALLY_ANSWERED để giảng viên xem lại thay vì bị loại khỏi danh sách.
- Failure/không căn cứ: Nếu không có chat/transcript đủ liên quan, câu hỏi ở UNANSWERED và không có bằng chứng trả lời.
- Correction: Giảng viên có thể thêm câu hỏi mới vào chat demo, refresh workspace, chạy tổng hợp lại và tạo summary mới.
- Khi bị đòi ngoài phạm vi: Nếu cần gửi mail thật, auth thật hoặc deploy production, prototype chỉ chuẩn bị dữ liệu, chưa tự gửi.
- Case đặc thù domain: Nếu câu hỏi nhắc tới token limit, prompt engineering, vector database hoặc model cost, local rules kiểm tra entity để tránh đánh dấu answered khi context chỉ gần nghĩa chung chung.

## §7. Kiểm Thử
- Chiều chất lượng:
  - Question detection: phân biệt câu hỏi thật với chat thường.
  - Dedup: gom đúng các câu hỏi cùng ý, không gom câu khác ý.
  - Answer detection: xác định ANSWERED, PARTIALLY_ANSWERED, UNANSWERED dựa trên evidence.
  - Session-level ranking: câu hỏi chưa trả lời thật phải xuất hiện trong Top 10 cho giảng viên.
- Golden set:
  - File: `backend/data/golden_set.json`.
  - Hiện có 21 atomic cases: 5 question_detection, 6 dedup, 10 answer_detection.
  - Cần bổ sung trước CP6: 20 session-level unresolved groups để đo Recall@10.
- Quality bar chốt:
  - Atomic golden set đạt ít nhất 90% overall và không chiều nào dưới 80%.
  - Recall@10 unresolved questions đạt ít nhất 85%.
  - Số cụ thể: đạt nếu ít nhất 17/20 nhóm câu hỏi thật sự chưa được trả lời xuất hiện trong Top 10 danh sách gửi giảng viên.
- Kết quả hiện tại:
| Ngày chạy | Bộ kiểm thử | Kết quả |
|---|---|---|
| 2026-09-17 | `python scripts/eval_golden.py` | question_detection 5/5, dedup 6/6, answer_detection 10/10, overall 21/21 = 100% |
| 2026-09-17 | `pnpm run lint` | Pass |
| 2026-09-17 | `pnpm run build` | Pass |

## §8. Phân Công & Kế Hoạch
| Thành viên | Vai trò | Phạm vi phụ trách |
|---|---|---|
| Bùi Hoàng Anh | AI & Quality Evaluation | Phụ trách phần AI: nhận diện câu hỏi, kiểm tra câu hỏi đã được trả lời hay chưa, thiết kế prompt cho model và xử lý fallback khi model lỗi. |
| Nguyễn Mai Hoàng Thiện | Backend & Data Processing | Phụ trách backend và xử lý dữ liệu: xây dựng các API để frontend gọi, quản lý dữ liệu buổi học trong SQLite, xử lý dữ liệu chat/transcript đầu vào và chuẩn bị dữ liệu cho phần AI tổng hợp câu hỏi. |
| Nguyễn Tiến Đạt | UI & Demo Flow | Phụ trách phần giao diện và demo: xây dựng dashboard cho giảng viên, màn thời khóa biểu, chat lớp học, màn tổng hợp Top-K câu hỏi, lịch sử bản lưu và luồng demo end-to-end. |

- Willing users + kế hoạch validation:
  - Mời ít nhất 2 bạn đóng vai giảng viên trong một buổi học demo real-time. Trong lúc meeting đang diễn ra, các bạn quan sát dashboard cập nhật câu hỏi học viên và đánh dấu nhóm câu hỏi nào cần được nhắc lại hoặc trả lời ngay.
  - Mời 3-5 bạn đóng vai học viên gửi câu hỏi trong chat với các kiểu khác nhau: câu hỏi mới, câu hỏi lặp ý, câu hỏi đã được giảng viên trả lời miệng, câu hỏi chưa được trả lời.
  - Sau demo, so sánh danh sách Top-K của hệ thống với đánh giá của giảng viên để cập nhật golden set session-level và kiểm tra chỉ số Recall@10.
- Multi-prototype:
  - Prototype 1 - After-class summary: hệ thống tổng hợp câu hỏi sau buổi học để giảng viên xem lại và lưu lịch sử.
  - Prototype 2 - Real-time meeting assistant: hệ thống cập nhật nhóm câu hỏi ngay trong lúc lớp học đang diễn ra, giúp giảng viên biết câu nào đang được hỏi nhiều hoặc chưa được xử lý.
  - Hướng ưu tiên tiếp theo là real-time meeting assistant, vì nó giúp giảng viên phản ứng ngay trong buổi học thay vì chỉ xử lý sau khi lớp kết thúc.

## §9. Changelog
| Thời điểm | Đổi gì | Vì sao |
|---|---|---|
| 2026-09-17 | Viết spec từ template sang lát cắt VLearn Tutor | Cần bản spec có mục tiêu, quality bar và flow rõ ràng |
| 2026-09-17 | Chốt số đo Recall@10 >= 85%, tương đương 17/20 nhóm unresolved | Cần số cụ thể để bảo vệ prototype |
| 2026-09-17 | Hoàn thiện phân công nhóm theo 3 mảng AI, Data, UI | Mỗi thành viên có phạm vi rõ để chuẩn bị thuyết trình và demo |
