from rag.ingestion.table_markdown import html_table_to_markdown, prepare_table_content

ROWSPAN_HTML = (
    "<table border=1 style='margin: auto; word-wrap: break-word;'>"
    "<tr>"
    "<td style='text-align: center; word-wrap: break-word;'>구분</td>"
    "<td style='text-align: center; word-wrap: break-word;'>소속</td>"
    "<td style='text-align: center; word-wrap: break-word;'>성명/ 직함</td>"
    "</tr>"
    "<tr>"
    '<td rowspan="3">내부</td>'
    "<td style='text-align: center; word-wrap: break-word;'>경영관리국 인사팀</td>"
    "<td style='text-align: center; word-wrap: break-word;'>박정수 팀장</td>"
    "</tr>"
    "<tr>"
    "<td style='text-align: center; word-wrap: break-word;'>기획조정실 BIZ혁신팀</td>"
    "<td style='text-align: center; word-wrap: break-word;'>오명진 팀장</td>"
    "</tr>"
    "<tr>"
    "<td style='text-align: center; word-wrap: break-word;'>전략마케팅국 영업정책팀</td>"
    "<td style='text-align: center; word-wrap: break-word;'>박세진 팀장</td>"
    "</tr>"
    "<tr>"
    '<td rowspan="3">외부</td>'
    "<td style='text-align: center; word-wrap: break-word;'>한국자활복지개발원</td>"
    "<td style='text-align: center; word-wrap: break-word;'>박수민 차장</td>"
    "</tr>"
    "<tr>"
    "<td style='text-align: center; word-wrap: break-word;'>한국무역보험공사 AI혁신팀</td>"
    "<td style='text-align: center; word-wrap: break-word;'>이승율 부팀장</td>"
    "</tr>"
    "<tr>"
    "<td style='text-align: center; word-wrap: break-word;'>대한무역투자진흥공사</td>"
    "<td style='text-align: center; word-wrap: break-word;'>이영일 팀장<br>※평가위원및일정은상황따라변동가능</td>"
    "</tr>"
    "</table>"
)


def test_html_table_to_markdown_expands_rowspan():
    md = html_table_to_markdown(ROWSPAN_HTML)
    assert "<table" not in md
    assert "style=" not in md
    lines = [line for line in md.splitlines() if line.startswith("|")]
    # header + sep + 6 data rows
    assert len(lines) >= 8
    assert "내부" in lines[2]
    assert "내부" in lines[3]  # rowspan filled
    assert "내부" in lines[4]
    assert "오명진" in lines[3]
    assert "외부" in lines[5]
    assert "외부" in lines[6]
    assert "이승율" in lines[6]


def test_prepare_table_content_passthrough_pipe_markdown():
    table = "| a | b |\n| --- | --- |\n| 1 | 2 |"
    assert prepare_table_content(table) == table


def test_prepare_table_content_converts_html():
    html = "<table><tr><td>a</td><td>b</td></tr><tr><td>1</td><td>2</td></tr></table>"
    out = prepare_table_content(html)
    assert out.startswith("|")
    assert "<td" not in out
