# Validation

Thư mục này chứa toàn bộ bộ kiểm thử chất lượng của dự án **VLearn Tutor – Ưu tiên nhóm câu hỏi học viên cần giảng viên chú ý**.

## Cấu trúc

```
validation/
├── README.md               # File này
├── run_validation.py       # Script tổng hợp chạy toàn bộ validation
├── session_cases.json      # Golden cases session-level (Precision@10)
└── eval_session.py         # Đánh giá Precision@10 session-level
```

## Các bộ kiểm thử

| Bộ kiểm thử | Script | Tiêu chí pass |
|---|---|---|
| Atomic golden set (21 cases) | `backend/scripts/eval_golden.py` | ≥ 90% overall, không chiều nào < 80% |
| Session-level Precision@10 | `validation/eval_session.py` | ≥ 70% (≥ 7/10 nhóm được xác nhận đáng xem) |

## Cách chạy

### Chạy toàn bộ (khuyến nghị)

```bash
cd backend
python ../validation/run_validation.py
```

### Chạy từng phần

```bash
# Atomic golden set
cd backend
python scripts/eval_golden.py

# Session-level Precision@10
cd backend
python ../validation/eval_session.py
```

## Quality bar (theo §7 spec)

- **Atomic golden set**: ≥ 90% overall, không chiều nào < 80%
  - question_detection: 5/5
  - dedup: 6/6
  - answer_detection: 10/10
- **Precision@10**: ≥ 70% (≥ 7/10 nhóm được giảng viên xác nhận đáng xem)

## Kết quả lần chạy gần nhất

| Ngày | Bộ kiểm thử | Kết quả |
|---|---|---|
| 2026-09-17 | eval_golden.py | question_detection 5/5, dedup 6/6, answer_detection 10/10 → 100% |
| 2026-09-17 | pnpm run lint | Pass |
| 2026-09-17 | pnpm run build | Pass |
