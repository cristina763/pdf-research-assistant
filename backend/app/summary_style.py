"""Question-depth policy for summaries, independent of PDF identity."""
import re
from .presentation import table_requested, numeric_requested


def detailed_summary(question):
    return table_requested(question) or numeric_requested(question) or bool(re.search(
        r'\b(?:detailed|comprehensive|exhaustive|rankings?)\b|\btable\s+\d+\b|詳細|詳盡|完整數值|排序', question, re.I))


SUMMARY_STYLE = '''
FINAL SUMMARY PRESENTATION (overrides earlier summary presentation guidance):
For a default whole-document summary aim for 200-350 English words or 300-500 Chinese characters in the visible answer, following the user's language preference. This is a soft target: never truncate or omit an important finding to fit it.
Cover the purpose, core method, evaluation and main experimental findings, important limitations or counterexamples, and conclusion. Integrate caveats into the relevant category. Use short paragraphs, not a catalogue of sections or variants. Do not invent missing limitations.
Summarize qualitative empirical findings and conclusions in your own source-backed words, including supported exceptions; empirical source IDs may support these statements. Do not generate numerical comparisons, universal winner claims, statistical significance or causal claims unsupported by the source. Keep Arabic digits and percentages out of generated statements; exact values remain in the source evidence.
Do not repeat long quotations, complete tables, every variant definition or every ranking in the summary. Full original evidence and validated numeric tables remain available separately. source_quotes selects additional evidence for inspection, not text to append to the default answer.
If the user explicitly asks for detail, tables, or numbers, follow that depth instead of the default length target.
'''
