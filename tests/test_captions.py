from hub import captions


def test_ass_color_is_bgr():
    assert captions.ass_color("#6a50a3") == "&H00A3506A"


def test_healthcare_word_fixes():
    assert captions.fix_words("my patience love it") == "my patients love it"
    assert captions.fix_words("ask a Dietician") == "ask a dietitian"


def test_words_in_range_shifts_to_zero(transcript):
    words = captions.words_in_range(transcript, 5.0, 15.0)
    assert words[0]["start"] == 0.0
    assert all(0 <= w["start"] <= 10.1 for w in words)
    assert len(words) == 20


def test_three_word_caps_chunks(transcript):
    words = captions.words_in_range(transcript, 5.0, 10.0)
    chunks = captions.chunk_words(words)
    assert chunks[0][2] == "WORD1_0 WORD1_1 PATIENTS"
    assert all(len(text.split()) <= 3 for _, _, text in chunks)
    # each chunk stays up until the next one starts
    assert chunks[0][1] == chunks[1][0]


def test_number_rejoin():
    tx = {"duration": 5, "segments": [{"words": [
        {"start": 0.0, "end": 0.3, "word": "8"}, {"start": 0.3, "end": 0.6, "word": ",463"},
        {"start": 0.7, "end": 1.0, "word": "patients"}]}]}
    words = captions.words_in_range(tx, 0, 5)
    assert [w["text"] for w in words] == ["8,463", "patients"]


def test_write_ass_uses_brand_colors(tmp_path, transcript):
    brand = {"colors": {"hook": {"bg": "#1F4E79", "fg": "#FFFFFF"}}}
    chunks = captions.chunk_words(captions.words_in_range(transcript, 0, 10))
    out = captions.write_ass(chunks, "Stop icing {your} knee", brand, tmp_path / "c.ass")
    text = out.read_text()
    assert "&H00794E1F" in text                     # hook background in ASS byte order
    assert "STOP ICING (YOUR) KNEE" in text          # caps, braces made safe for ASS
    assert text.count("Dialogue:") == len(chunks) + 1
