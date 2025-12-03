import io
from dataclasses import dataclass, asdict
from typing import List, Optional
import fitz  # PyMuPDF

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
    # 估算正文字号：用“字数>20 的行”的中位数作为正文字号
    body_sizes = [l.size for l in lines if len(l.text) > 20]
    body_size_median = (sorted(body_sizes)[len(body_sizes)//2] if body_sizes else 0)

    for l in lines:
        # 标题判断条件
        l.is_heading = (
            l.text and 
            l.size >= body_size_median + size_delta_threshold and 
            (l.spacing_before is None or l.spacing_before >= spacing_threshold) and 
            len(l.text) <= max_title_len and 
            not l.text.strip().endswith(("。", ".", "!", "！", "?", "？"))
        )

    return lines


# =========================
# 生成 DataFrame 查看结果
# =========================
def display_lines(lines: List[LineInfo]):
    """将解析出来的行信息展示为 DataFrame，方便查看"""
    import pandas as pd
    # 将 LineInfo 转换为字典，并生成 DataFrame
    df = pd.DataFrame([asdict(l) for l in lines])
    return df


# =========================
# 主程序
# =========================
def main(file_bytes: bytes):
    # 解析 PDF
    lines = parse_pdf_lines(file_bytes)
    if not lines:
        print("未能从 PDF 中解析出任何行，请检查文件是否正常。")
        return

    # 标记标题候选
    lines = mark_heading_candidates(lines)

    # 显示结果
    df = display_lines(lines)

    # 打印标记为标题的行
    print(f"共解析 {len(lines)} 行，其中疑似标题行如下：")
    df_headings = df[df["is_heading"] == True]  # 获取疑似标题
    if df_headings.empty:
        print("未识别出疑似标题行，请尝试调整阈值。")
    else:
        print(df_headings[['page', 'line_index', 'text', 'size', 'spacing_before']])


# 测试代码：上传文件并运行
if __name__ == "__main__":
    with open("/mnt/data/humam resource management.pdf", "rb") as f:
        file_bytes = f.read()
    main(file_bytes)