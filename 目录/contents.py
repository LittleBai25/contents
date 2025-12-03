import io
from dataclasses import dataclass, asdict
from typing import List, Optional
import fitz  # PyMuPDF
import streamlit as st
import pandas as pd

# 数据结构定义
@dataclass
class LineInfo:
    page: int
    line_index: int
    text: str
    font: str
    size: float
    x0: float
    y0: float
    x1: float
    y1: float
    spacing_before: Optional[float] = None
    spacing_after: Optional[float] = None
    is_heading: bool = False

# PDF解析与特征提取
def parse_pdf_lines(file_bytes: bytes) -> List[LineInfo]:
    """使用 PyMuPDF 按“行”解析 PDF，抽取字体 / 字号 / 坐标等特征。"""
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    all_lines: List[LineInfo] = []

    for page_index, page in enumerate(doc):
        page_dict = page.get_text("dict")
        blocks = page_dict.get("blocks", [])
        line_counter = 0

        for b in blocks:
            for line in b.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue

                # 拼接一行文字
                text = "".join(s.get("text", "") for s in spans).strip()
                if not text:
                    continue

                main_span = spans[0]
                font = main_span.get("font", "")
                size = float(main_span.get("size", 0.0))
                x0, y0, x1, y1 = line.get("bbox", (0, 0, 0, 0))

                line_info = LineInfo(
                    page=page_index + 1,
                    line_index=line_counter,
                    text=text,
                    font=font,
                    size=size,
                    x0=float(x0),
                    y0=float(y0),
                    x1=float(x1),
                    y1=float(y1),
                )
                all_lines.append(line_info)
                line_counter += 1

    all_lines = compute_line_spacing(all_lines)
    return all_lines

def compute_line_spacing(lines: List[LineInfo]) -> List[LineInfo]:
    by_page = {}
    for line in lines:
        by_page.setdefault(line.page, []).append(line)

    new_lines: List[LineInfo] = []
    for page, page_lines in by_page.items():
        page_lines_sorted = sorted(page_lines, key=lambda l: l.y0)
        prev_line: Optional[LineInfo] = None
        for l in page_lines_sorted:
            if prev_line is None:
                l.spacing_before = None
            else:
                spacing = l.y0 - prev_line.y1
                l.spacing_before = float(spacing) if spacing >= 0 else None
            prev_line = l
            new_lines.append(l)

    return new_lines

# 统计不同字体、字号、段前段后间距的出现次数
def generate_statistics(df: pd.DataFrame):
    # 字体统计
    font_counts = df['font'].value_counts()
    
    # 字号统计
    size_counts = df['size'].value_counts()

    # 字体和字号组合统计
    font_size_counts = df.groupby(['font', 'size']).size().reset_index(name='count')

    # 段前间距统计
    spacing_before_counts = df['spacing_before'].fillna(0).value_counts()

    # 段后间距统计
    spacing_after_counts = df['spacing_after'].fillna(0).value_counts()

    # 段前和段后间距组合统计
    df['spacing_combined'] = df.apply(lambda x: (x['spacing_before'], x['spacing_after']), axis=1)
    spacing_combined_counts = df['spacing_combined'].value_counts()

    return font_counts, size_counts, font_size_counts, spacing_before_counts, spacing_after_counts, spacing_combined_counts

# Streamlit界面
def main():
    st.set_page_config(page_title="PDF 标题识别实验工具", layout="wide")
    st.title("📄 PDF 特征统计工具")

    uploaded_file = st.file_uploader("请上传一个 PDF 文件", type=["pdf"])

    if not uploaded_file:
        st.info("👆 请先上传一个 PDF 文件。")
        return

    file_bytes = uploaded_file.read()
    st.write(f"已上传文件: {uploaded_file.name}")

    with st.spinner("正在解析 PDF..."):
        lines = parse_pdf_lines(file_bytes)

    if not lines:
        st.error("未能从 PDF 中解析出任何行，请检查文件是否正常。")
        return

    st.success(f"解析完成，共获得 {len(lines)} 行文本。")

    # 转换为DataFrame
    df = pd.DataFrame([asdict(l) for l in lines])

    # 生成统计数据
    font_counts, size_counts, font_size_counts, spacing_before_counts, spacing_after_counts, spacing_combined_counts = generate_statistics(df)

    # 显示统计数据
    st.subheader("字体统计")
    st.write(font_counts)

    st.subheader("字号统计")
    st.write(size_counts)

    st.subheader("字体和字号组合统计")
    st.write(font_size_counts)

    st.subheader("段前间距统计")
    st.write(spacing_before_counts)

    st.subheader("段后间距统计")
    st.write(spacing_after_counts)

    st.subheader("段前和段后间距组合统计")
    st.write(spacing_combined_counts)

if __name__ == "__main__":
    main()