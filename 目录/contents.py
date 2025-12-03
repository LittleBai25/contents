import io
from dataclasses import dataclass, asdict
from typing import List, Optional
import fitz  # PyMuPDF
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt

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

# 分类：根据字体大小、段前间距来简单分类文本行
def classify_lines(df: pd.DataFrame, size_threshold=14, spacing_threshold=10):
    """
    通过字体大小、段前间距来简单分类文本行。
    - 标题：字体大，段前间距大
    - 正文：字体小，段前间距较小
    """
    df['classification'] = '正文'  # 默认是正文
    df.loc[(df['size'] >= size_threshold) & (df['spacing_before'] >= spacing_threshold), 'classification'] = '标题'
    
    # 其他规则可以在这里添加
    return df

# 标题候选识别
def mark_heading_candidates(
    lines: List[LineInfo],
    size_delta_threshold: float = 2.0,
    spacing_threshold: float = 4.0,
    max_title_len: int = 80,
) -> List[LineInfo]:
    body_sizes = [l.size for l in lines if len(l.text) > 20]
    body_size_median = (sorted(body_sizes)[len(body_sizes)//2] if body_sizes else 0)

    for l in lines:
        l.is_heading = (
            l.text and 
            l.size >= body_size_median + size_delta_threshold and 
            (l.spacing_before is None or l.spacing_before >= spacing_threshold) and 
            len(l.text) <= max_title_len and 
            not l.text.strip().endswith(("。", ".", "!", "！", "?", "？"))
        )

    return lines

# Streamlit界面
def main():
    st.set_page_config(page_title="PDF 标题识别实验工具", layout="wide")
    st.title("📄 PDF 标题候选识别 & 特征提取工具")

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

    # 转换为DataFrame进行分类
    df = pd.DataFrame([asdict(l) for l in lines])

    # 分类：通过字体大小和段前间距进行简单分类
    df_classified = classify_lines(df)

    # 统计分类结果
    classification_counts = df_classified['classification'].value_counts()
    classification_percentage = df_classified['classification'].value_counts(normalize=True) * 100

    # 显示分类统计结果
    st.subheader("分类统计结果")
    st.write("各类文本行的数量：")
    st.write(classification_counts)
    
    st.write("各类文本行的占比：")
    st.write(classification_percentage)

    # 可视化分类占比
    fig, ax = plt.subplots()
    classification_percentage.plot(kind='bar', ax=ax, color=['blue', 'green'])
    ax.set_title('文本分类占比')
    ax.set_ylabel('占比 (%)')
    ax.set_xlabel('分类')
    st.pyplot(fig)

    # 标记标题候选
    lines = mark_heading_candidates(lines)

    # 显示标记为标题的行
    st.subheader("疑似标题行")
    df_headings = df_classified[df_classified["classification"] == "标题"]
    if df_headings.empty:
        st.write("未识别出疑似标题行，请尝试调整参数。")
    else:
        st.dataframe(df_headings[['page', 'line_index', 'text', 'font', 'size', 'spacing_before']])

if __name__ == "__main__":
    main()