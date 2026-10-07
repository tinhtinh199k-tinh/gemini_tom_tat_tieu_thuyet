import os
import sys
import time
import json
import re
from pathlib import Path
from typing import List, Optional, Tuple

import streamlit as st

try:
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup
except ImportError:
    st.error("⚠️ Vui lòng cài đặt: pip install ebooklib beautifulsoup4")

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

# CẤU HÌNH THƯ MỤC
BASE_DIR = Path(__file__).resolve().parent
FOLDER_EPUB_GOC = BASE_DIR / "1.Epub_Gốc"
FOLDER_TXT_TU_EPUB = BASE_DIR / "2.Txt_Từ Epub"
FOLDER_TXT_BAN_TOM_TAT = BASE_DIR / "3.Txt_Bản tóm tắt"
FOLDER_EPUB_BAN_TOM_TAT = BASE_DIR / "4.Epub_Bản tóm tắt"
CONFIG_DIR = BASE_DIR / "config"

for folder in [FOLDER_EPUB_GOC, FOLDER_TXT_TU_EPUB, FOLDER_TXT_BAN_TOM_TAT, FOLDER_EPUB_BAN_TOM_TAT, CONFIG_DIR]:
    folder.mkdir(parents=True, exist_ok=True)

def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', str(s))]

def clean_key(key: str) -> str:
    if not key:
        return ""
    return key.strip().strip('"').strip("'").strip()

# NẠP KEY (HỖ TRỢ CẢ FILE TXT LẪN STREAMLIT SECRETS)
def load_all_keys() -> List[str]:
    keys = []
    # 1. Đọc từ Streamlit Secrets (nếu cấu hình trên Cloud)
    if "GEMINI_API_KEYS" in st.secrets:
        raw = st.secrets["GEMINI_API_KEYS"]
        if isinstance(raw, list):
            keys.extend([clean_key(k) for k in raw if clean_key(k)])
        elif isinstance(raw, str):
            keys.extend([clean_key(k) for k in raw.split("\n") if clean_key(k)])

    # 2. Đọc từ file txt
    txt_files = ["api_keys.txt", "api_key.txt", "keys.txt", "key.txt"]
    for name in txt_files:
        fpath = BASE_DIR / name
        if fpath.exists():
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                regex_keys = re.findall(r'AIzaSy[A-Za-z0-9_-]{33}', content)
                for k in regex_keys:
                    ck = clean_key(k)
                    if ck and ck not in keys:
                        keys.append(ck)
            except Exception:
                pass
            break
    return keys

FALLBACK_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash"
]

class GeminiManager:
    def __init__(self, keys: List[str], preferred_model: str = "gemini-3.5-flash-lite", delay_between_calls: float = 2.0):
        self.keys = [clean_key(k) for k in keys if clean_key(k)]
        self.current_key_idx = 0
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
            raise ValueError("Không tìm thấy API Key nào!")

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
        raise RuntimeError("Tất cả API keys và Models đều thất bại. Hãy kiểm tra lại Key!")

# GIAO DIỆN
st.set_page_config(page_title="AI Novel Studio Mobile", page_icon="📚", layout="wide")

with st.sidebar:
    st.header("⚙️ Cấu hình")
    selected_model = st.selectbox("Model AI mặc định:", options=FALLBACK_MODELS, index=0)
    loaded_keys = load_all_keys()
    st.info(f"🔑 Đã nạp **{len(loaded_keys)}** API Key.")
    
    st.markdown("---")
    st.subheader("📤 Tải file EPUB từ điện thoại lên:")
    uploaded_file = st.file_uploader("Chọn file .epub từ máy:", type=["epub"])
    if uploaded_file is not None:
        save_path = FOLDER_EPUB_GOC / uploaded_file.name
        with open(save_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        st.success(f"✅ Đã tải lên `{uploaded_file.name}` thành công!")

tabs = st.tabs(["1. 📖 EPUB to TXT", "2. 📝 Tóm Tắt Bằng Gemini", "3. 📦 TXT to EPUB"])

# TAB 1
with tabs[0]:
    st.subheader("📖 Tách EPUB thành TXT")
    epub_files = sorted(list(FOLDER_EPUB_GOC.glob("*.epub")), key=lambda p: p.name.lower())

    if not epub_files:
        st.warning("⚠️ Chưa có file EPUB nào. Hãy dùng nút 'Tải file EPUB' ở cột bên trái để tải truyện lên!")
    else:
        for idx, ef in enumerate(epub_files, start=1):
            st.markdown(f"**{idx}.** `{ef.name}`")

        sel_num = st.number_input("Chọn số thứ tự file:", min_value=1, max_value=len(epub_files), value=1, step=1, key="t1_num")
        selected_epub = epub_files[sel_num - 1]
        target_folder = FOLDER_TXT_TU_EPUB / selected_epub.stem

        if st.button("🚀 Bắt đầu tách thành TXT", key="btn_t1"):
            target_folder.mkdir(parents=True, exist_ok=True)
            book = epub.read_epub(str(selected_epub))
            items = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
            chapter_idx = 1
            p_bar = st.progress(0.0)

            for i, item in enumerate(items):
                soup = BeautifulSoup(item.get_content(), "html.parser")
                text = soup.get_text(separator="\n").strip()
                if len(text) < 150:
                    continue
                cleaned = "\n\n".join([line.strip() for line in text.split("\n") if line.strip()])
                with open(target_folder / f"Chương {chapter_idx:04d}.txt", "w", encoding="utf-8") as f:
                    f.write(cleaned)
                chapter_idx += 1
                p_bar.progress(float((i + 1) / len(items)))

            st.success(f"🎉 Đã tách thành công {chapter_idx - 1} chương vào `{target_folder.name}`!")

# TAB 2
with tabs[1]:
    st.subheader("📝 Tóm Tắt Bằng Gemini")
    subdirs_t2 = sorted([d for d in FOLDER_TXT_TU_EPUB.iterdir() if d.is_dir()], key=lambda p: p.name.lower())

    if not subdirs_t2:
        st.warning("⚠️ Chưa có truyện nào được tách. Hãy chạy Tab 1 trước!")
    else:
        for idx, d in enumerate(subdirs_t2, start=1):
            st.markdown(f"**{idx}.** `{d.name}`")

        sel_num_t2 = st.number_input("Chọn số thứ tự truyện:", min_value=1, max_value=len(subdirs_t2), value=1, step=1, key="t2_num")
        selected_dir_t2 = subdirs_t2[sel_num_t2 - 1]
        summary_dir_name = f"Tóm tắt_{selected_dir_t2.name}"
        summarize_dest = FOLDER_TXT_BAN_TOM_TAT / summary_dir_name

        delay_sec = st.slider("Giãn cách giữa các lần gọi AI (giây):", min_value=1.0, max_value=5.0, value=2.0, step=0.5)

        if st.button("🚀 Bắt đầu Tóm tắt", key="btn_t2"):
            if not loaded_keys:
                st.error("⚠️ Chưa có API Key nào!")
            else:
                summarize_dest.mkdir(parents=True, exist_ok=True)
                txt_files = sorted([f for f in selected_dir_t2.glob("*.txt") if f.is_file()], key=natural_sort_key)
                gemini = GeminiManager(loaded_keys, preferred_model=selected_model, delay_between_calls=delay_sec)
                p_bar = st.progress(0.0)
                msg_ph = st.empty()

                for idx, tf in enumerate(txt_files, start=1):
                    out_f = summarize_dest / f"{tf.stem}_tomtat.txt"
                    if out_f.exists():
                        p_bar.progress(idx / len(txt_files))
                        continue

                    msg_ph.text(f"🤖 Đang tóm tắt {tf.stem} ({idx}/{len(txt_files)})...")
                    with open(tf, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()

                    prompt = f"Hãy tóm tắt ngắn gọn, mạch lạc diễn biến chính chương này (250-400 từ):\n\n{content[:15000]}"
                    try:
                        res = gemini.generate(prompt)
                        with open(out_f, "w", encoding="utf-8") as f:
                            f.write(res.strip())
                    except Exception as e:
                        st.warning(f"Lỗi tại {tf.stem}: {e}")

                    p_bar.progress(idx / len(txt_files))

                st.success(f"🎉 Hoàn thành tóm tắt vào `{summary_dir_name}`!")

# TAB 3
with tabs[2]:
    st.subheader("📦 Đóng gói TXT to EPUB")
    subdirs_t3 = sorted([d for d in FOLDER_TXT_BAN_TOM_TAT.iterdir() if d.is_dir()], key=lambda p: p.name.lower())

    if not subdirs_t3:
        st.warning("⚠️ Chưa có bản tóm tắt nào. Hãy chạy Tab 2 trước!")
    else:
        for idx, d in enumerate(subdirs_t3, start=1):
            st.markdown(f"**{idx}.** `{d.name}`")

        sel_num_t3 = st.number_input("Chọn số thứ tự thư mục tóm tắt:", min_value=1, max_value=len(subdirs_t3), value=1, step=1, key="t3_num")
        selected_dir_t3 = subdirs_t3[sel_num_t3 - 1]

        raw_name = selected_dir_t3.name
        clean_name = raw_name[len("Tóm tắt_"):] if raw_name.startswith("Tóm tắt_") else raw_name
        final_epub_name = f"Tóm tắt_{clean_name}.epub"
        final_epub_path = FOLDER_EPUB_BAN_TOM_TAT / final_epub_name

        if st.button("🚀 Gộp thành file EPUB", key="btn_t3"):
            sum_files = sorted([f for f in selected_dir_t3.glob("*.txt") if f.is_file()], key=natural_sort_key)
            book = epub.EpubBook()
            book.set_identifier(f"id_{int(time.time())}")
            book.set_title(f"Tóm tắt_{clean_name}")
            book.set_language("vi")
            book.add_author("AI Novel Summarizer")

            spine, toc = ["nav"], []
            for idx, sf in enumerate(sum_files, start=1):
                with open(sf, "r", encoding="utf-8", errors="ignore") as f:
                    c_text = f.read()
                p_tags = "".join(f"<p>{line.strip()}</p>" for line in c_text.split("\n") if line.strip())
                chap_item = epub.EpubHtml(title=sf.stem, file_name=f"chap_{idx:04d}.xhtml", lang="vi")
                chap_item.content = f"<h2>{sf.stem}</h2>\n{p_tags}".encode("utf-8")
                book.add_item(chap_item)
                spine.append(chap_item)
                toc.append(chap_item)

            book.toc = tuple(toc)
            book.add_item(epub.EpubNcx())
            book.add_item(epub.EpubNav())
            book.spine = spine
            epub.write_epub(str(final_epub_path), book, {})
            st.success(f"🎉 Đã tạo xong `{final_epub_name}`!")

        # NÚT TẢI EPUB TRỰC TIẾP VỀ ĐIỆN THOẠI
        if final_epub_path.exists():
            with open(final_epub_path, "rb") as f:
                st.download_button(
                    label=f"📥 Tải file `{final_epub_name}` về điện thoại",
                    data=f,
                    file_name=final_epub_name,
                    mime="application/epub+zip",
                    use_container_width=True
                )