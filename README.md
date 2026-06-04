Quản lý Phân quyền trong Odoo
Khi định nghĩa quyền trực tiếp trong code Python (ví dụ: nhóm Sale Rep với quyền Sale/Own Document), nếu sau đó chỉnh sửa thủ công thành Sale/Admin trên giao diện, thì mỗi lần update module phân quyền, hệ thống sẽ revert về quyền gốc trong code — mất toàn bộ thay đổi thủ công.
Cách giải quyết ---> Nếu chưa chắc chắn về cấu hình quyền, xóa phần định nghĩa quyền trong code Python, hoặc để trắng hoàn toàn
Ưu điểm

⁠Cố định bộ quyền chuẩn, nhất quán cho từng Role
Nếu lỡ sửa sai thủ công → update lại module là khôi phục được
T⁠iết kiệm thời gian khi gán user: dùng ngay, không cần cấu hình tay
⁠Bảo toàn cấu hình: khi deploy sang database mới, quyền được tạo lại tự động

Nhược điểm: 

⁠Mọi chỉnh sửa thủ công trên giao diện đối với quyền gốc sẽ bị ghi đè khi update
Thiếu linh hoạt nếu nghiệp vụ còn thay đổi thường xuyên module
