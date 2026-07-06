"""Small generated PDF byte fixtures for parser tests."""


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_text_pdf(page_texts: list[str]) -> bytes:
    objects: list[bytes] = []

    pages_object_number = 2
    first_page_object_number = 3
    next_object_number = first_page_object_number

    page_object_numbers: list[int] = []
    content_object_numbers: list[int] = []

    for _page_text in page_texts:
        page_object_numbers.append(next_object_number)
        next_object_number += 1
        content_object_numbers.append(next_object_number)
        next_object_number += 1

    font_object_number = next_object_number

    catalog = b"<< /Type /Catalog /Pages 2 0 R >>"
    pages = (
        f"<< /Type /Pages /Kids "
        f"[{' '.join(f'{number} 0 R' for number in page_object_numbers)}] "
        f"/Count {len(page_object_numbers)} >>"
    ).encode()

    objects.append(catalog)
    objects.append(pages)

    for _page_object_number, content_object_number, page_text in zip(
        page_object_numbers,
        content_object_numbers,
        page_texts,
        strict=True,
    ):
        page = (
            f"<< /Type /Page /Parent {pages_object_number} 0 R "
            f"/MediaBox [0 0 612 792] "
            f"/Contents {content_object_number} 0 R "
            f"/Resources << /Font << /F1 {font_object_number} 0 R >> >> >>"
        ).encode()
        stream_text = (
            f"BT /F1 24 Tf 100 700 Td ({_escape_pdf_text(page_text)}) Tj ET"
        ).encode()
        content = (
            b"<< /Length "
            + str(len(stream_text)).encode()
            + b" >>\nstream\n"
            + stream_text
            + b"\nendstream"
        )

        objects.append(page)
        objects.append(content)

    font = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    objects.append(font)

    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]

    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode())
        output.extend(obj)
        output.extend(b"\nendobj\n")

    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")

    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())

    output.extend(
        f"trailer\n<< /Root 1 0 R /Size {len(objects) + 1} >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )

    return bytes(output)
