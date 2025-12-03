import io
import html
from dataclasses import dataclass, asdict
from typing import List, Optional

import fitz  # PyMuPDF
import pandas as pd
import streamlit as st


# =========================
# 数据结构定义
# =========================
@dataclass
class LineInfo:
    page: int
    line_index: int  # 当前页内行号
    text: str
    font: str
    size: float
    x0: float
    y0: float
    x1: float
    y1: float
    spacing_before: Optional[float] = None  # 与上一行底部的垂直距离
    is_heading: bool = False                # 是否疑似标题


# =========================
# PDF 解析与特征提取
# =========================
def parse_pdf_lines(file_bytes: bytes) -> List[LineInfo]:
    """使用 PyMuPDF 按“行”解析 PDF，抽取字体 / 字号 / 坐标等特征。"""
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    all_lines: List[LineInfo] = []

    for page_index, page in enumerate(doc):
        page_dict = page.get_text("dict")
        blocks = page_dict.get("blocks", [])
        line_counter = 0

        # PyMuPDF 的结构：page -> blocks -> lines -> spans
        for b in blocks:
            for line in b.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue

                # 将一行内的多个 span 拼成一行文字
                text = "".join(s.get("text", "") for s in spans).strip()
                if not text:
                    continue

                main_span = spans[0]
                font = main_span.get("font", "")
                size = float(main_span.get("size", 0.0))
                x0, y0, x1, y1 = line.get("bbox", (0, 0, 0, 0))

                line_info = LineInfo(
                    page=page_index + 1,  # 页码从 1 开始更直观
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

    # 计算每一页内的 spacing_before
    all_lines = compute_line_spacing(all_lines)
    return all_lines


def compute_line_spacing(lines: List[LineInfo]) -> List[LineInfo]:
    """在同一页内按 y0 排序，计算与上一行底部的垂直距离，记为 spacing_before。"""
    # 按页分组
    by_page = {}
    for line in lines:
        by_page.setdefault(line.page, []).append(line)

    new_lines: List[LineInfo] = []
    for page, page_lines in by_page.items():
        # 按 y0 从小到大排序（注意：PyMuPDF 的坐标原点在左上）
        page_lines_sorted = sorted(page_lines, key=lambda l: l.y0)

        prev_line: Optional[LineInfo] = None
        for l in page_lines_sorted:
            if prev_line is None:
                l.spacing_before = None
            else:
                spacing = l.y0 - prev_line.y1
                # 如果出现负值，说明可能是多栏排版或坐标略乱，这里简单兜底
                l.spacing_before = float(spacing) if spacing >= 0 else None
            prev_line = l
            new_lines.append(l)

    # 保持原有顺序不重要，后续都按 page + y0 来看
    return new_lines


# =========================
# 标题候选识别（规则版）
# =========================
def mark_heading_candidates(
    lines: List[LineInfo],
    size_delta_threshold: float = 2.0,
    spacing_threshold: float = 4.0,
    max_title_len: int = 80,
) -> List[LineInfo]:
    """基于字号 / 段前间距 / 文本长度，使用简单规则标记疑似标题。"""

    # 估算正文字号：这里用“字数>20 的行”的中位数作为正文字号
    body_sizes = [
        l.size for l in lines
        if len(l.text) > 20  # 过滤掉短行（短行更可能是标题）
    ]
    if not body_sizes:
        return lines

    body_sizes_sorted = sorted(body_sizes)
    mid = len(body_sizes_sorted) // 2
    if len(body_sizes_sorted) % 2 == 1:
        body_size_median = body_sizes_sorted[mid]
    else:
        body_size_median = (body_sizes_sorted[mid - 1] + body_sizes_sorted[mid]) / 2

    for l in lines:
        # 基础条件：有文字
        if not l.text:
            l.is_heading = False
            continue

        # 条件 1：字号比正文大
        cond_size = l.size >= body_size_median + size_delta_threshold

        # 条件 2：段前间距足够大（为空则不作为必要条件）
        cond_spacing = True
        if l.spacing_before is not None:
            cond_spacing = l.spacing_before >= spacing_threshold

        # 条件 3：字数不宜过长（标题一般不会特别长）
        cond_len = len(l.text) <= max_title_len

        # 条件 4：通常标题不会以句号结束（可选）
        cond_punct = not l.text.strip().endswith(("。", ".", "!", "！", "?", "？"))

        l.is_heading = cond_size and cond_spacing and cond_len and cond_punct

    return lines


# =========================
# 生成简单 HTML（带数据属性）
# =========================
def build_html_from_lines(lines: List[LineInfo]) -> str:
    """把行信息序列化成一个简单 HTML，方便后续目录比对使用。"""
    parts = ['<div class="pdf-lines">']
    for l in sorted(lines, key=lambda x: (x.page, x.y0)):
        safe_text = html.escape(l.text)
        attrs = [
            f'data-page="{l.page}"',
            f'data-font="{html.escape(l.font)}"',
            f'data-size="{l.size:.2f}"',
        ]
        if l.spacing_before is not None:
            attrs.append(f'data-spacing-before="{l.spacing_before:.2f}"')
        attrs.append(f'data-is-heading="{str(l.is_heading).lower()}"')

        tag = "h2" if l.is_heading else "p"
        parts.append(f'  <{tag} {" ".join(attrs)}>{safe_text}</{tag}>')
    parts.append("</div>")
    return "\n".join(parts)


# =========================
# Streamlit 界面
# =========================
def main():
    st.set_page_config(page_title="PDF 标题识别实验工具", layout="wide")
    st.title("📄 PDF 标题候选识别 & HTML 转换（实验版）")

    st.markdown(
        """
        这个小工具会帮你做几件事：
        1. **解析 PDF**：按“行”抽取文本、字体、字号、坐标；
        2. **计算段前间距**：估计每行与上一行之间的垂直间距；
        3. **基于规则识别疑似标题**：你可以调节阈值，观察哪些行被标记为标题；
        4. **生成简单 HTML**：每一行带有 `data-` 属性，后续可用于目录比对与校对。
        """
    )

    uploaded_file = st.file_uploader("请上传一个 PDF 文件", type=["pdf"])

    if not uploaded_file:
        st.info("👆 请先上传一个 PDF 文件。")
        return

    file_bytes = uploaded_file.read()

    with st.spinner("正在解析 PDF..."):
        lines = parse_pdf_lines(file_bytes)

    if not lines:
        st.error("未能从 PDF 中解析出任何行，请检查文件是否正常。")
        return

    st.success(f"解析完成，共获得 {len(lines)} 行文本。")

    # -------------------------
    # 参数调节区
    # -------------------------
    st.sidebar.header("标题识别参数（规则调节）")

    size_delta_threshold = st.sidebar.slider(
        "标题字号比正文大多少（pt）视为候选标题",
        min_value=0.5,
        max_value=10.0,
        value=2.0,
        step=0.5,
    )

    spacing_threshold = st.sidebar.slider(
        "段前间距阈值（单位：PDF 坐标，大致对应像素）",
        min_value=0.0,
        max_value=50.0,
        value=4.0,
        step=1.0,
    )

    max_title_len = st.sidebar.slider(
        "标题最大字数",
        min_value=10,
        max_value=150,
        value=80,
        step=5,
    )

    lines = mark_heading_candidates(
        lines,
        size_delta_threshold=size_delta_threshold,
        spacing_threshold=spacing_threshold,
        max_title_len=max_title_len,
    )

    # 转成 DataFrame 方便查看
    df = pd.DataFrame([asdict(l) for l in lines])

    # 页面筛选
    page_numbers = sorted(df["page"].unique())
    selected_page = st.selectbox("选择要查看的页码", page_numbers)

    df_page = df[df["page"] == selected_page].copy()
    df_page_display = df_page[
        [
            "page",
            "line_index",
            "text",
            "font",
            "size",
            "spacing_before",
            "is_heading",
            "x0",
            "y0",
            "x1",
            "y1",
        ]
    ]

    st.subheader(f"第 {selected_page} 页行级信息")
    st.dataframe(df_page_display, use_container_width=True, height=500)

    # 单独展示当前页的标题候选
    st.subheader(f"第 {selected_page} 页疑似标题行")
    df_headings = df_page[df_page["is_heading"] == True]  # noqa: E712
    if df_headings.empty:
        st.write("当前页未识别出疑似标题行，请尝试调整左侧的参数。")
    else:
        for _, row in df_headings.iterrows():
            st.markdown(
                f"- **[{row['page']}:{row['line_index']}]** "
                f"(size={row['size']:.1f}, spacing_before={row['spacing_before']})："
                f"`{row['text']}`"
            )

    # 生成 HTML 并展示
    st.subheader("生成的简单 HTML（带 data- 属性，可用于后续目录比对）")
    html_str = build_html_from_lines(lines)

    with st.expander("查看 HTML 源码"):
        st.code(html_str, language="html")

    st.markdown("**渲染预览（仅简单展示，不保证与 PDF 排版一致）：**")
    st.markdown(
        """
        <div style="border:1px solid #ccc; padding:1rem; max-height:400px; overflow:auto;">
        """
        + html_str +
        "</div>",
        unsafe_allow_html=True,
    )

    # 提供 HTML 下载
    html_bytes = html_str.encode("utf-8")
    st.download_button(
        label="💾 下载 HTML 文件（用于后续处理）",
        data=html_bytes,
        file_name=f"{uploaded_file.name.rsplit('.', 1)[0]}_lines.html",
        mime="text/html",
    )


if __name__ == "__main__":
    main()