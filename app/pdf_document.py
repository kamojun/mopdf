from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import fitz  # PyMuPDF
from PySide6.QtGui import QImage


@dataclass
class TocEntry:
    level: int          # 1=章, 2=節, 3=小節 ...
    title: str
    page: int           # 0-indexed 物理ページ番号
    dest: dict = field(default_factory=dict)  # PyMuPDF destination info


@dataclass
class PageLabelRange:
    start_page: int     # 0-indexed 物理ページ番号
    style: str          # "D"=アラビア数字, "r"=ローマ小文字, "R"=ローマ大文字,
                        # "a"=英字小文字, "A"=英字大文字, ""=ラベルなし
    prefix: str         # プレフィックス文字列
    first_num: int      # 開始番号


STYLE_LABELS = {
    "D": "アラビア数字",
    "r": "ローマ数字（小）",
    "R": "ローマ数字（大）",
    "a": "英字（小）",
    "A": "英字（大）",
    "": "なし",
}


class PdfDocument:
    def __init__(self) -> None:
        self._doc: Optional[fitz.Document] = None
        self._path: Optional[Path] = None

    @property
    def is_open(self) -> bool:
        return self._doc is not None

    @property
    def path(self) -> Optional[Path]:
        return self._path

    @property
    def page_count(self) -> int:
        if self._doc is None:
            return 0
        return self._doc.page_count

    def open(self, path: str | Path) -> None:
        if self._doc is not None:
            self._doc.close()
        self._path = Path(path)
        self._doc = fitz.open(str(self._path))

    def close(self) -> None:
        if self._doc is not None:
            self._doc.close()
            self._doc = None
            self._path = None

    # ------------------------------------------------------------------
    # 目次 (TOC / Bookmarks)
    # ------------------------------------------------------------------

    def get_toc(self) -> list[TocEntry]:
        if self._doc is None:
            return []
        raw = self._doc.get_toc(simple=False)
        entries = []
        for item in raw:
            level, title, page, dest = item[0], item[1], item[2], item[3]
            entries.append(TocEntry(
                level=level,
                title=title,
                page=page - 1,  # PyMuPDFは1-indexed, 内部は0-indexed
                dest=dest if isinstance(dest, dict) else {},
            ))
        return entries

    def set_toc(self, entries: list[TocEntry]) -> None:
        if self._doc is None:
            return
        raw = []
        for e in entries:
            dest = e.dest if e.dest else {"kind": fitz.LINK_GOTO, "page": e.page, "to": fitz.Point(0, 0)}
            raw.append([e.level, e.title, e.page + 1, dest])
        self._doc.set_toc(raw)

    # ------------------------------------------------------------------
    # ページラベル
    # ------------------------------------------------------------------

    def get_page_labels(self) -> list[PageLabelRange]:
        if self._doc is None:
            return []
        try:
            raw = self._doc.get_page_labels()
        except Exception:
            return []
        result = []
        for item in raw:
            result.append(PageLabelRange(
                start_page=item.get("startpage", 0),
                style=item.get("style", "D"),
                prefix=item.get("prefix", ""),
                first_num=item.get("firstpagenum", 1),
            ))
        return result

    def set_page_labels(self, ranges: list[PageLabelRange]) -> None:
        if self._doc is None:
            return
        raw = []
        for r in ranges:
            raw.append({
                "startpage": r.start_page,
                "style": r.style,
                "prefix": r.prefix,
                "firstpagenum": r.first_num,
            })
        self._doc.set_page_labels(raw)

    def get_page_label_for(self, page_index: int) -> str:
        """0-indexedの物理ページ番号から論理ページラベルを返す"""
        if self._doc is None:
            return str(page_index + 1)
        try:
            return self._doc[page_index].get_label()
        except Exception:
            return ""

    def find_page_by_label(self, label: str) -> int:
        """ページラベル文字列から0-indexed物理ページ番号を返す。見つからなければ-1。"""
        if self._doc is None:
            return -1
        label = label.strip()
        for i in range(self._doc.page_count):
            try:
                if self._doc[i].get_label() == label:
                    return i
            except Exception:
                pass
        return -1

    # ------------------------------------------------------------------
    # レンダリング
    # ------------------------------------------------------------------

    def get_page_size(self, page_index: int, zoom: float = 1.5) -> tuple[int, int]:
        """レンダリングせずにページの幅・高さ（px）を返す"""
        if self._doc is None:
            return (0, 0)
        rect = self._doc[page_index].rect
        return (int(rect.width * zoom), int(rect.height * zoom))

    def get_text_in_rect(self, page_index: int, rect_px: tuple[float, float, float, float], zoom: float) -> str:
        """ピクセル座標の矩形内のテキストを抽出する。rect_px=(x0,y0,x1,y1)"""
        if self._doc is None:
            return ""
        x0, y0, x1, y1 = rect_px
        pdf_rect = fitz.Rect(x0 / zoom, y0 / zoom, x1 / zoom, y1 / zoom)
        try:
            return self._doc[page_index].get_textbox(pdf_rect).strip()
        except Exception:
            return ""

    def render_page(self, page_index: int, zoom: float = 1.5) -> QImage:
        if self._doc is None:
            raise RuntimeError("No document open")
        page = self._doc[page_index]
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
        return img.copy()  # detach from pix lifetime

    # ------------------------------------------------------------------
    # 保存
    # ------------------------------------------------------------------

    def save(self, path: str | Path | None = None) -> None:
        if self._doc is None:
            return
        target = Path(path) if path else self._path
        if target == self._path:
            self._doc.save(str(target), incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
        else:
            self._doc.save(str(target))
