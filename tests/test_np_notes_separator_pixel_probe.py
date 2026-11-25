"""Offscreen Qt rendering diagnostics for horizontal separator alternatives."""
import os, sys, unittest
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtGui import QColor, QTextCursor, QTextBlockFormat, QTextFrameFormat, QTextLength, QTextTableFormat, QTextTableCellFormat
from PySide6.QtWidgets import QApplication, QTextEdit

def probe(mode):
    te=QTextEdit()
    te.setFixedSize(640,260)
    te.setStyleSheet("QTextEdit { background-color: #2d2d2d; color: #eeeeee; border: 0px; }")
    te.setPlainText("Alpha")
    cur=te.textCursor();cur.movePosition(QTextCursor.End)
    cur.insertBlock()
    if mode=="hr":
        cur.insertHtml('<hr width="100%" size="2" />')
    elif mode=="table":
        fmt=QTextTableFormat();fmt.setBorder(0);fmt.setCellPadding(0);fmt.setCellSpacing(0);fmt.setWidth(QTextLength(QTextLength.PercentageLength,100))
        table=cur.insertTable(1,1,fmt)
        cell=table.cellAt(0,0)
        cf=cell.format().toTableCellFormat();cf.setBackground(QColor("#a0a0a0"));cell.setFormat(cf)
    elif mode=="block":
        fmt=QTextBlockFormat();fmt.setBackground(QColor("#a0a0a0"));fmt.setLineHeight(2,QTextBlockFormat.FixedHeight)
        cur.setBlockFormat(fmt)
        cur.insertText(" ")
    elif mode=="frame":
        fmt=QTextFrameFormat();fmt.setBorder(2);fmt.setBorderBrush(QColor("#a0a0a0"));fmt.setWidth(QTextLength(QTextLength.PercentageLength,100))
        cur.insertFrame(fmt)
    te.show();QApplication.processEvents()
    pic=te.viewport().grab().toImage().convertToFormat(4)
    hits=[]
    for y in range(25,min(pic.height()-20,180)):
        v=0
        for x in range(35,pic.width()-35):
            c=pic.pixelColor(x,y)
            if c.red()>105 and c.green()>105 and c.blue()>105:
                v+=1
        hits.append((v,y))
    hits.sort(reverse=True)
    return hits[:7],te.toHtml()[te.toHtml().find("<body"):][-720:]

class Probe(unittest.TestCase):
    def test_variants(self):
        app=QApplication.instance() or QApplication([])
        for mode in ("hr","table","block","frame"):
            top,html=probe(mode)
            print("PIXEL_PROBE",mode,top,"HTML_TAIL",repr(html[-400:]),flush=True)
if __name__=="__main__":
    unittest.main()
