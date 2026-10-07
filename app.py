import os
import sys
import time
import json
import re
from pathlib import Path
from typing import List, Optional, Tuple

import streamlit as st

# Thư viện xử lý EPUB & HTML
try:
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup
except ImportError:
    st.error("⚠️ Vui lòng cài đặt: pip install ebooklib beautifulsoup4")

# Thư viện Google GenAI
USE_NEW_GENAI = False
try:
    from google import genai
    from google.genai import types
    USE_NEW_GENAI = True
except ImportError:
    try:
        import google.generativeai as legacy_genai
        USE_NEW_GENAI = False
    except ImportError:
        st.error("⚠️ Vui lòng cài đặt: pip install google-genai")

# -------------------------------------------------------------
# CẤU HÌNH THƯ MỤC LÀM VIỆC TẠM TRONG PHIÊN
# -------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
FOLDER_EPUB_GOC = BASE_DIR / "1.Epub_Gốc"
FOLDER_TXT_TU_EPUB = BASE_DIR / "2.Txt_Từ Epub"
FOLDER_TXT_BAN_TOM_TAT = BASE_DIR / "3.Txt_Bản tóm tắt"
FOLDER_EPUB_BAN_TOM_TAT = BASE_DIR / "4.Epub_Bản tóm tắt"

for folder in [FOLDER_EPUB_GOC, FOLDER_TXT_TU_EPUB, FOLDER_TXT_BAN_TOM_TAT, FOLDER_EPUB_BAN_TOM_TAT]:
    folder.mkdir(parents=True, exist_ok=True)

# -------------------------------------------------------------
# TIỆN ÍCH HỆ THỐNG
# -------------------------------------------------------------
def natural_sort_key(s):
    """Sắp xếp tự nhiên theo số chương: Chương 1, Chương 2 ... Chương 10."""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', str(s))]

def clean_key(key: str) -> str:
    """Làm sạch key, loại bỏ khoảng trắng và dấu nháy kép/đơn."""
    if not key:
        return ""
    return key.strip().strip('"').strip("'").strip()

FALLBACK_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash"
]

def test_single_key(api_key: str, model_name: str = "gemini-3.5-flash-lite") -> Tuple[bool, str]:
    """Kiểm tra trực tiếp xem API Key của người dùng có hoạt động không."""
    cleaned = clean_key(api_key)
    if not cleaned:
        return False, "Bạn chưa nhập Key."
    if not cleaned.startswith("AIzaSy"):
        return False, "Key không đúng định dạng (Google API Key bắt đầu bằng 'AIzaSy')."

    test_models = [model_name] + [m for m in FALLBACK_MODELS if m != model_name]
    for m in test_models:
        try:
            if USE_NEW_GENAI:
                client = genai.Client(api_key=cleaned)
                resp = client.models.generate_content(model=m, contents="Trả lời đúng một từ: OK")
                if resp and resp.text:
                    return True, f"Kết nối tốt với {m}!"
            else:
                legacy_genai.configure(api_key=cleaned)
                model = legacy_genai.GenerativeModel(m)
                resp = model.generate_content("Trả lời đúng một từ: OK")
                if resp and resp.text:
                    return True, f"Kết nối tốt với {m}!"
        except Exception as e:
            err_str = str(e)
            if "401" in err_str:
                return False, "Lỗi 401 UNAUTHENTICATED: Key sai hoặc chưa kích hoạt API!"
            if "429" in err_str:
                return True, "Key hợp lệ nhưng tạm hết quota (429 Rate limit)."
            continue

    return False, "Không kết nối được. Hãy kiểm tra lại Key trên Google AI Studio."

# -------------------------------------------------------------
# QUẢN LÝ GEMINI
# -------------------------------------------------------------
class GeminiManager:
    def __init__(self, keys: List[str], preferred_model: str = "gemini-3.5-flash-lite", delay_between_calls: float = 2.0):
        self.keys = [clean_key(k) for k in keys if clean_key(k)]
        self.current_key_idx = 0
        self.preferred_model = preferred_model
        self.delay = delay_between_calls
        self.models = [preferred_model] + [m for m in FALLBACK_MODELS if m != preferred_model]

    def get_current_key(self) -> Optional[str]:
        if not self.keys:
            return None
        return self.keys[self.current_key_idx % len(self.keys)]

    def rotate_key(self):
        if self.keys:
            self.current_key_idx = (self.current_key_idx + 1) % len(self.keys)

    def generate(self, prompt: str) -> str:
        if not self.keys:
            raise ValueError("Chưa có API Key nào được nhập!")

        for model_name in self.models:
            for _ in range(len(self.keys)):
                api_key = self.get_current_key()
                try:
                    if USE_NEW_GENAI:
                        client = genai.Client(api_key=api_key)
                        response = client.models.generate_content(model=model_name, contents=prompt)
                        text = response.text if response and response.text else ""
                    else:
                        legacy_genai.configure(api_key=api_key)
                        model = legacy_genai.GenerativeModel(model_name=model_name)
                        response = model.generate_content(prompt)
                        text = response.text if response and response.text else ""

                    time.sleep(self.delay)
                    return text
                except Exception:
                    self.rotate_key()
                    time.sleep(1.0)

        raise RuntimeError("Gọi AI thất bại. Hãy kiểm tra lại Key và hạn mức tài khoản!")

# -------------------------------------------------------------
# GIAO DIỆN STREAMLIT
# -------------------------------------------------------------
st.set_page_config(page_title="AI Novel Studio - Tóm Tắt Tiểu Thuyết", page_icon="📚", layout="wide")

# KHỞI TẠO BỘ NHỚ TỰ NHẬP KEY CHO MỖI NGƯỜI DÙNG
if "user_keys" not in st.session_state:
    st.session_state["user_keys"] = []

# SIDEBAR: NGƯỜI DÙNG TỰ NHẬP KEY RIÊNG
with st.sidebar:
    st.header("🔑 Cấu hình Gemini cá nhân")
    st.caption("Key được bảo mật riêng trong phiên duyệt web của bạn, không bị lưu trữ.")

    user_key_input = st.text_input(
        "Nhập Google Gemini API Key của bạn:",
        type="password",
        placeholder="AIzaSy...",
        help="Lấy key miễn phí từ Google AI Studio (aistudio.google.com/apikey)"
    )

    c_btn1, c_btn2 = st.columns([1, 1])
    with c_btn1:
        if st.button("➕ Thêm Key", use_container_width=True):
            cleaned_k = clean_key(user_key_input)
            if cleaned_k and cleaned_k not in st.session_state["user_keys"]:
                st.session_state["user_keys"].append(cleaned_k)
                st.success("Đã thêm key!")
                st.rerun()

    with c_btn2:
        if st.button("🗑️ Xóa hết", use_container_width=True):
            st.session_state["user_keys"] = []
            st.rerun()

    active_keys = st.session_state["user_keys"]
    st.info(f"Đang kích hoạt: **{len(active_keys)}** key.")

    if active_keys:
        if st.button("🔍 Kiểm tra hoạt động Key", use_container_width=True):
            with st.spinner("Đang kiểm tra kết nối..."):
                for idx, k in enumerate(active_keys, start=1):
                    ok, detail = test_single_key(k)
                    short_k = f"{k[:6]}...{k[-4:]}"
                    if ok:
                        st.success(f"✅ Key {idx} ({short_k}): {detail}")
                    else:
                        st.error(f"❌ Key {idx} ({short_k}): {detail}")

    st.markdown("---")
    selected_model = st.selectbox("Mô hình AI:", options=FALLBACK_MODELS, index=0)

    st.markdown("---")
    st.markdown("""
    💡 **Cách lấy Key miễn phí trong 10 giây:**
    1. Truy cập [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
    2. Bấm **Create API key**
    3. Sao chép và dán vào ô trên.
    """)

# 3 TAB CHÍNH
tabs = st.tabs([
    "1. 📖 EPUB to TXT",
    "2. 📝 Tóm Tắt Bằng Gemini",
    "3. 📦 TXT to EPUB"
])

# =============================================================
# TAB 1: EPUB to TXT (Không cần API Key)
# =============================================================
with tabs[0]:
    st.subheader("📖 Tách file EPUB thành từng chương TXT")
    st.caption("Tải file EPUB từ thiết bị của bạn lên và giải nén thành các chương sạch.")

    uploaded_epub = st.file_uploader("📤 Chọn file .epub từ máy của bạn:", type=["epub"], key="upload_epub_t1")
    if uploaded_epub is not None:
        save_path = FOLDER_EPUB_GOC / uploaded_epub.name
        with open(save_path, "wb") as f:
            f.write(uploaded_epub.getbuffer())
        st.success(f"✅ Đã tải file `{uploaded_epub.name}` vào hệ thống!")

    epub_files = sorted(list(FOLDER_EPUB_GOC.glob("*.epub")), key=lambda p: p.name.lower())

    if not epub_files:
        st.info("💡 Hãy dùng ô bên trên để tải lên 1 file EPUB.")
    else:
        st.write(f"### Danh sách file EPUB:")
        for idx, ef in enumerate(epub_files, start=1):
            st.markdown(f"**{idx}.** `{ef.name}`")

        sel_num = st.number_input(
            "Nhập số thứ tự file EPUB muốn tách:",
            min_value=1,
            max_value=len(epub_files),
            value=1,
            step=1,
            key="tab1_sel_num"
        )
        selected_epub = epub_files[sel_num - 1]
        target_folder = FOLDER_TXT_TU_EPUB / selected_epub.stem

        st.info(f"👉 File đã chọn: **{selected_epub.name}** | Đích: `{FOLDER_TXT_TU_EPUB.name}/{target_folder.name}`")

        if st.button("🚀 Bắt đầu tách thành TXT", key="btn_start_epub_to_txt"):
            target_folder.mkdir(parents=True, exist_ok=True)
            try:
                with st.spinner("Đang đọc cấu trúc EPUB..."):
                    book = epub.read_epub(str(selected_epub))
                    items = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))

                chapter_idx = 1
                progress_bar = st.progress(0.0)

                for i, item in enumerate(items):
                    soup = BeautifulSoup(item.get_content(), "html.parser")
                    text = soup.get_text(separator="\n").strip()

                    if len(text) < 150:
                        continue

                    cleaned_lines = [line.strip() for line in text.split("\n") if line.strip()]
                    cleaned_text = "\n\n".join(cleaned_lines)

                    chap_filename = f"Chương {chapter_idx:04d}.txt"
                    out_path = target_folder / chap_filename
                    with open(out_path, "w", encoding="utf-8") as f:
                        f.write(cleaned_text)

                    chapter_idx += 1
                    progress_bar.progress(float((i + 1) / len(items)))

                st.success(f"🎉 Hoàn thành! Đã tạo {chapter_idx - 1} chương vào `{FOLDER_TXT_TU_EPUB.name}/{target_folder.name}`.")
            except Exception as e:
                st.error(f"❌ Lỗi: {e}")

# =============================================================
# TAB 2: TÓM TẮT BẰNG GEMINI (Sử dụng Key cá nhân của người dùng)
# =============================================================
with tabs[1]:
    st.subheader("📝 Tóm Tắt Bằng Gemini")
    st.caption("AI tóm tắt từng chương và lưu vào thư mục `Tóm tắt_[tên của tiểu thuyết]`.")

    subdirs_tab2 = sorted([d for d in FOLDER_TXT_TU_EPUB.iterdir() if d.is_dir()], key=lambda p: p.name.lower())

    if not subdirs_tab2:
        st.warning("⚠️ Chưa có truyện nào được tách TXT. Hãy chuẩn bị ở Tab 1 trước!")
    else:
        for idx, d in enumerate(subdirs_tab2, start=1):
            st.markdown(f"**{idx}.** `{d.name}`")

        sel_num_tab2 = st.number_input(
            "Nhập số thứ tự truyện cần tóm tắt:",
            min_value=1,
            max_value=len(subdirs_tab2),
            value=1,
            step=1,
            key="tab2_sel_num"
        )
        selected_dir_tab2 = subdirs_tab2[sel_num_tab2 - 1]

        novel_title = selected_dir_tab2.name
        summary_dir_name = f"Tóm tắt_{novel_title}"
        summarize_dest_folder = FOLDER_TXT_BAN_TOM_TAT / summary_dir_name

        st.info(f"👉 Truyện đã chọn: **{novel_title}**\n\n📂 Thư mục đích: `{FOLDER_TXT_BAN_TOM_TAT.name}/{summary_dir_name}`")
        delay_sec = st.slider("Giãn cách giữa các lần gọi AI (giây):", min_value=1.0, max_value=5.0, value=2.0, step=0.5)

        if st.button("🚀 Bắt đầu Tóm tắt bằng Gemini", key="btn_start_summarize"):
            if not active_keys:
                st.error("⚠️ BẠN CHƯA NHẬP KEY: Vui lòng nhập Google Gemini API Key của bạn ở thanh bên trái (Sidebar) để bắt đầu!")
            else:
                summarize_dest_folder.mkdir(parents=True, exist_ok=True)
                txt_files = sorted([f for f in selected_dir_tab2.glob("*.txt") if f.is_file()], key=natural_sort_key)

                if not txt_files:
                    st.error("Không tìm thấy file chương nào!")
                else:
                    gemini = GeminiManager(active_keys, preferred_model=selected_model, delay_between_calls=delay_sec)
                    p_bar = st.progress(0.0)
                    msg_ph = st.empty()

                    for idx, tf in enumerate(txt_files, start=1):
                        out_summary_file = summarize_dest_folder / f"{tf.stem}_tomtat.txt"
                        if out_summary_file.exists():
                            p_bar.progress(idx / len(txt_files))
                            continue

                        msg_ph.text(f"🤖 Đang tóm tắt {tf.stem} ({idx}/{len(txt_files)})...")
                        try:
                            with open(tf, "r", encoding="utf-8", errors="ignore") as f:
                                chapter_content = f.read()

                            prompt_sum = f"""Hãy đọc kỹ nội dung chương tiểu thuyết sau và tóm tắt ngắn gọn, mạch lạc (khoảng 250 - 400 từ):
[NỘI DUNG CHƯƠNG]
{chapter_content[:15000]}

YÊU CẦU:
1. Diễn biến và hành động chính của các nhân vật.
2. Quyết định then chốt và bước ngoặt sự kiện.
3. Chi tiết quan trọng mới về bối cảnh, bảo vật hoặc công pháp (nếu có).
"""
                            summary_res = gemini.generate(prompt_sum)
                            with open(out_summary_file, "w", encoding="utf-8") as f:
                                f.write(summary_res.strip())

                        except Exception as e:
                            st.warning(f"⚠️ Gặp lỗi tại {tf.stem}: {e}")

                        p_bar.progress(idx / len(txt_files))

                    st.success(f"🎉 Hoàn thành tóm tắt toàn bộ truyện! Đã lưu tại `{FOLDER_TXT_BAN_TOM_TAT.name}/{summary_dir_name}`.")

# =============================================================
# TAB 3: TXT to EPUB (Có nút tải file trực tiếp về máy)
# =============================================================
with tabs[2]:
    st.subheader("📦 Đóng gói TXT tóm tắt thành file EPUB")
    st.caption("Gộp các chương tóm tắt thành file EPUB chuẩn và tải trực tiếp về điện thoại/máy tính.")

    subdirs_tab3 = sorted([d for d in FOLDER_TXT_BAN_TOM_TAT.iterdir() if d.is_dir()], key=lambda p: p.name.lower())

    if not subdirs_tab3:
        st.warning("⚠️ Chưa có bản tóm tắt nào. Hãy chạy Tab 2 trước!")
    else:
        for idx, d in enumerate(subdirs_tab3, start=1):
            st.markdown(f"**{idx}.** `{d.name}`")

        sel_num_tab3 = st.number_input(
            "Nhập số thứ tự thư mục muốn đóng gói:",
            min_value=1,
            max_value=len(subdirs_tab3),
            value=1,
            step=1,
            key="tab3_sel_num"
        )
        selected_dir_tab3 = subdirs_tab3[sel_num_tab3 - 1]

        folder_raw_name = selected_dir_tab3.name
        if folder_raw_name.startswith("Tóm tắt_"):
            clean_novel_name = folder_raw_name[len("Tóm tắt_"):]
            final_epub_name = f"Tóm tắt_{clean_novel_name}.epub"
            epub_book_title = f"Tóm tắt_{clean_novel_name}"
        else:
            final_epub_name = f"Tóm tắt_{folder_raw_name}.epub"
            epub_book_title = f"Tóm tắt_{folder_raw_name}"

        final_epub_path = FOLDER_EPUB_BAN_TOM_TAT / final_epub_name

        st.info(f"👉 Thư mục nguồn: **{selected_dir_tab3.name}**\n\n📖 File EPUB xuất ra: `{final_epub_name}`")

        if st.button("🚀 Gộp thành file EPUB", key="btn_create_epub"):
            sum_files = sorted([f for f in selected_dir_tab3.glob("*.txt") if f.is_file()], key=natural_sort_key)
            if not sum_files:
                st.error("Không có file tóm tắt nào trong thư mục này!")
            else:
                try:
                    book = epub.EpubBook()
                    book.set_identifier(f"id_{int(time.time())}")
                    book.set_title(epub_book_title)
                    book.set_language("vi")
                    book.add_author("AI Novel Summarizer")

                    spine = ["nav"]
                    toc = []

                    for idx, sf in enumerate(sum_files, start=1):
                        with open(sf, "r", encoding="utf-8", errors="ignore") as f:
                            c_text = f.read()

                        p_tags = "".join(f"<p>{line.strip()}</p>" for line in c_text.split("\n") if line.strip())
                        html_content = f"<h2>{sf.stem}</h2>\n{p_tags}"

                        chap_item = epub.EpubHtml(
                            title=sf.stem,
                            file_name=f"chap_{idx:04d}.xhtml",
                            lang="vi"
                        )
                        chap_item.content = html_content.encode("utf-8")
                        book.add_item(chap_item)
                        spine.append(chap_item)
                        toc.append(chap_item)

                    book.toc = tuple(toc)
                    book.add_item(epub.EpubNcx())
                    book.add_item(epub.EpubNav())
                    book.spine = spine

                    epub.write_epub(str(final_epub_path), book, {})
                    st.success(f"🎉 Đã tạo thành công file: `{final_epub_name}`!")
                except Exception as e:
                    st.error(f"❌ Lỗi: {e}")

        # NÚT TẢI VỀ MÁY / ĐIỆN THOẠI
        if final_epub_path.exists():
            with open(final_epub_path, "rb") as f:
                st.download_button(
                    label=f"📥 Tải file `{final_epub_name}` về thiết bị",
                    data=f,
                    file_name=final_epub_name,
                    mime="application/epub+zip",
                    use_container_width=True
                )