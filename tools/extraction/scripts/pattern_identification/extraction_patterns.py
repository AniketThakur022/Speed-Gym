"""
Comprehensive extraction patterns for educational content.
Designed for ontology-based knowledge graph integration.
"""

import re
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
from pathlib import Path


# =============================================================================
# ENUMS & SCHEMAS
# =============================================================================

class DifficultyLevel(Enum):
    BEGINNER = "beginner"
    EASY = "easy"
    MEDIUM = "medium"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    HARD = "hard"
    EXPERT = "expert"


class ContentType(Enum):
    FIGURE = "figure"
    CHART = "chart"
    DIAGRAM = "diagram"
    TABLE = "table"
    IMAGE = "image"


@dataclass
class Position:
    line_start: int
    line_end: int
    col_start: int = 0
    col_end: int = 0


@dataclass
class FigureArtifact:
    marker_type: str
    identifier: str
    caption: Optional[str]
    url: Optional[str]
    file_path: Optional[str]
    position: Position
    references: list[str] = field(default_factory=list)
    table_data: Optional[list[list[str]]] = None


@dataclass
class SectionHeader:
    level: int
    title: str
    position: Position
    is_learning_objective: bool = False
    is_summary: bool = False


@dataclass
class LearningObjective:
    text: str
    position: Position
    section_context: Optional[str] = None


@dataclass
class KeyTakeaway:
    text: str
    position: Position
    bullet_point: bool = False


@dataclass
class Summary:
    text: str
    position: Position
    is_bulleted: bool = False


@dataclass
class AuthorNote:
    note_type: str
    content: str
    position: Position
    emoji: Optional[str] = None


@dataclass
class DifficultyTag:
    level: DifficultyLevel
    raw_text: str
    position: Position
    star_count: Optional[int] = None
    confidence: float = 1.0


@dataclass
class TrapOrMistake:
    marker: str
    content: str
    position: Position
    severity: str = "warning"
    emoji: Optional[str] = None


# =============================================================================
# REGEX PATTERNS
# =============================================================================

PATTERNS = {
    "figures": {
        "bracket_markers": re.compile(
            r'\[(FIGURE|CHART|DIAGRAM|IMAGE|TABLE)\s*(\d+)?\s*(?:[:\-]\s*([^\]]+))?\]',
            re.IGNORECASE
        ),
        "figure_headers": re.compile(
            r'\*\*\s*Figure\s+(\d+(?:\.\d+)?)\s*[:：]?\s*([^*]+)\s*\*\*',
            re.IGNORECASE
        ),
        "figure_headers_md": re.compile(
            r'^#{1,3}\s*Figure\s+(\d+(?:\.\d+)?)\s*[:：]?\s*(.+)$',
            re.MULTILINE | re.IGNORECASE
        ),
        "figure_caption_simple": re.compile(
            r'^Figure\s+(\d+(?:\.\d+)?)\s*[:：]\s*(.+)$',
            re.MULTILINE | re.IGNORECASE
        ),
        "see_figure_ref": re.compile(
            r'(?:see|refer to|in|as shown in)\s+(?:the\s+)?(figure|chart|diagram|table)\s*(\d+(?:\.\d+)?)',
            re.IGNORECASE
        ),
        "image_urls": re.compile(
            r'(?:!\[[^\]]*\]\s*\()?(https?://[^\s\)]+(?:png|jpg|jpeg|gif|svg|webp)(?:\?[^\s\)]*)?)',
            re.IGNORECASE
        ),
        "markdown_images": re.compile(
            r'!\[([^\]]*)\]\(([^)]+)\)',
        ),
        "image_paths": re.compile(
            r'(?:src=["\']|href=["\']|url\(["\']?)([^"\')\s]+\.(?:png|jpg|jpeg|gif|svg|webp))',
            re.IGNORECASE
        ),
    },
    "tables": {
        "markdown_table": re.compile(
            r'^\|[^|]+\|[ \t]*$\n'
            r'(?:\|[-:| ]+\|[ \t]*$\n)?'
            r'(?:\|[^|]+\|[ \t]*$\n?)+',
            re.MULTILINE
        ),
        "data_table_header": re.compile(
            r'^\s*([A-Za-z][A-Za-z0-9_\s]{2,30})\s*\|\s*([A-Za-z][A-Za-z0-9_\s]{2,30})',
            re.MULTILINE
        ),
        "table_marker": re.compile(
            r'\[TABLE\s*(\d+)?\s*(?:[:\-]\s*([^\]]+))?\]',
            re.IGNORECASE
        ),
    },
    "pedagogy": {
        "headers": re.compile(
            r'^(#{1,6})\s+(.+?)\s*$',
            re.MULTILINE
        ),
        "learning_objectives": re.compile(
            r'(?:^#{1,3}\s*(?:Learning\s+Objectives?|Objectives?|Goals?|Outcomes?)[\s\S]*?)(?=\n#{1,3}\s|\Z)',
            re.MULTILINE | re.IGNORECASE
        ),
        "lo_bullets": re.compile(
            r'^\s*[-*+]\s+(.+)$',
            re.MULTILINE
        ),
        "key_takeaway_marker": re.compile(
            r'(?:^#{1,3}\s*(?:Key\s+Takeaways?|Summary|Highlights?|Main\s+Points?)[\s\S]*?)(?=\n#{1,3}\s|\Z)',
            re.MULTILINE | re.IGNORECASE
        ),
        "takeaway_bullets": re.compile(
            r'^\s*[-*+]\s+\*\*([^*]+)\*\*[:：]?\s*(.+)$',
            re.MULTILINE
        ),
        "summary_marker": re.compile(
            r'(?:^#{1,3}\s*Summary[\s\S]*?)(?=\n#{1,3}\s|\Z)',
            re.MULTILINE | re.IGNORECASE
        ),
        "remember_marker": re.compile(
            r'^\s*\*\*(?:Remember|Key\s+Point|Important)\*\*[:：]?\s*(.+)$',
            re.MULTILINE
        ),
    },
    "author_notes": {
        "blockquote": re.compile(
            r'^>\s*(.+)$',
            re.MULTILINE
        ),
        "note_marker": re.compile(
            r'(?:^|\n)\s*[\-*]?\s*\*{0,2}(?:Note|Tip|Info|FYI)\*{0,2}[:：]\s*(.+?)(?=\n\n|\n[\-*]|\n#{1,3}|$)',
            re.MULTILINE | re.IGNORECASE | re.DOTALL
        ),
        "remember_important": re.compile(
            r'(?:^|\n)\s*[\-*]?\s*\*{0,2}(?:Remember|Important|Warning|Caution|Key\s+Point)\*{0,2}[:：]?\s*(.+?)(?=\n\n|\n[\-*]|\n#{1,3}|$)',
            re.MULTILINE | re.IGNORECASE | re.DOTALL
        ),
        "emoji_notes": re.compile(
            r'(💡|📝|📌|⚠️|❗|ℹ️|✨|🎯)[:：]?\s*(.+?)(?=\n\n|\n#{1,3}|$)',
            re.DOTALL
        ),
        "callout_block": re.compile(
            r'^>\s*[\*\[]?(Note|Tip|Warning|Important|Info)[\*\]]?[:：]?\s*(.+?)(?=\n(?:>\s*)?$|\n\n)',
            re.MULTILINE | re.IGNORECASE | re.DOTALL
        ),
    },
    "difficulty": {
        "explicit_level": re.compile(
            r'(?:Difficulty|Level|Complexity)\s*[:：]\s*(beginner|easy|medium|intermediate|advanced|hard|expert)',
            re.IGNORECASE
        ),
        "explicit_numeric": re.compile(
            r'(?:Difficulty|Level)[:：]?\s*(\d)(?:\s*/\s*(\d))?',
            re.IGNORECASE
        ),
        "star_rating": re.compile(
            r'([★☆])\1{0,4}',
        ),
        "implicit_beginner": re.compile(
            r'\b(?:introductory|basic|fundamental|beginner|getting\s+started|for\s+beginners|first\s+steps)\b',
            re.IGNORECASE
        ),
        "implicit_intermediate": re.compile(
            r'\b(?:intermediate|practical|hands-on|working\s+with|applying)\b',
            re.IGNORECASE
        ),
        "implicit_advanced": re.compile(
            r'\b(?:advanced|expert|challenging|complex|deep\s+dive|mastery|for\s+experts)\b',
            re.IGNORECASE
        ),
    },
    "traps": {
        "explicit_trap": re.compile(
            r'(?:^|\n)\s*[\-*]?\s*\*{0,2}(?:Common\s+Mistake|Trap|Pitfall|Gotcha|Watch\s+Out|Be\s+Careful)\*{0,2}[:：]?\s*(.+?)(?=\n\n|\n[\-*]|\n#{1,3}|$)',
            re.MULTILINE | re.IGNORECASE | re.DOTALL
        ),
        "students_often": re.compile(
            r'(?:^|\n)\s*[\-*]?\s*(?:Students|Learners|Developers|Users)\s+(?:often|frequently|sometimes)\s+(?:make|run\s+into|encounter|fall\s+for|struggle\s+with)\s+([^.]+\.?)',
            re.MULTILINE | re.IGNORECASE
        ),
        "warning_emoji": re.compile(
            r'(⚠️|⚠|🚨|⛔|❗|❌)[:：]?\s*(.+?)(?=\n\n|\n#{1,3}|\n[\-*]|$)',
            re.DOTALL
        ),
        "antipattern": re.compile(
            r"(?:^|\n)\s*[\-*]?\s*\*{0,2}(?:Anti-pattern|Bad\s+Practice|Don't\s+Do\s+This|Avoid)\*{0,2}[:：]?\s*(.+?)(?=\n\n|\n[\-*]|\n#{1,3}|$)",
            re.MULTILINE | re.IGNORECASE | re.DOTALL
        ),
        "careful_marker": re.compile(
            r'(?:^|\n)\s*[\-*]?\s*(?:Be\s+careful|Watch\s+out|Caution|Heads\s+up)[:：]?\s*(.+?)(?=\n\n|\n[\-*]|\n#{1,3}|$)',
            re.MULTILINE | re.IGNORECASE | re.DOTALL
        ),
    },
}


# =============================================================================
# EXTRACTION FUNCTIONS
# =============================================================================

def get_line_position(text: str, match_start: int) -> tuple[int, int]:
    """Get line number from character position."""
    lines_before = text[:match_start].split('\n')
    line_start = len(lines_before)
    line_end = line_start
    return line_start, line_end


def create_position(text: str, match_start: int, match_end: int) -> Position:
    """Create a Position object from match locations."""
    lines_before_start = text[:match_start].count('\n') + 1
    lines_before_end = text[:match_end].count('\n') + 1
    return Position(
        line_start=lines_before_start,
        line_end=lines_before_end
    )


def extract_figures_and_charts(text: str) -> list[FigureArtifact]:
    """Extract all figure, chart, diagram, and image references."""
    results = []
    used_positions = set()
    
    # Bracket markers [FIGURE N], [CHART], etc.
    for match in PATTERNS["figures"]["bracket_markers"].finditer(text):
        pos = create_position(text, match.start(), match.end())
        marker_type = match.group(1).lower()
        identifier = match.group(2) or ""
        caption = match.group(3)
        
        results.append(FigureArtifact(
            marker_type=marker_type,
            identifier=identifier,
            caption=caption.strip() if caption else None,
            url=None,
            file_path=None,
            position=pos
        ))
        used_positions.add((pos.line_start, pos.line_end))
    
    # Figure headers **Figure N: Title**
    for match in PATTERNS["figures"]["figure_headers"].finditer(text):
        pos = create_position(text, match.start(), match.end())
        if (pos.line_start, pos.line_end) in used_positions:
            continue
            
        results.append(FigureArtifact(
            marker_type="figure",
            identifier=match.group(1),
            caption=match.group(2).strip(),
            url=None,
            file_path=None,
            position=pos
        ))
    
    # Markdown Figure headers # Figure N: Title
    for match in PATTERNS["figures"]["figure_headers_md"].finditer(text):
        pos = create_position(text, match.start(), match.end())
        if (pos.line_start, pos.line_end) in used_positions:
            continue
            
        results.append(FigureArtifact(
            marker_type="figure",
            identifier=match.group(1),
            caption=match.group(2).strip(),
            url=None,
            file_path=None,
            position=pos
        ))
    
    # Simple Figure N: captions
    for match in PATTERNS["figures"]["figure_caption_simple"].finditer(text):
        pos = create_position(text, match.start(), match.end())
        if (pos.line_start, pos.line_end) in used_positions:
            continue
            
        results.append(FigureArtifact(
            marker_type="figure",
            identifier=match.group(1),
            caption=match.group(2).strip(),
            url=None,
            file_path=None,
            position=pos
        ))
    
    # Markdown images ![alt](url)
    for match in PATTERNS["figures"]["markdown_images"].finditer(text):
        pos = create_position(text, match.start(), match.end())
        alt_text = match.group(1)
        url = match.group(2)
        
        results.append(FigureArtifact(
            marker_type="image",
            identifier="",
            caption=alt_text if alt_text else None,
            url=url,
            file_path=None,
            position=pos
        ))
    
    # Standalone image URLs
    for match in PATTERNS["figures"]["image_urls"].finditer(text):
        pos = create_position(text, match.start(), match.end())
        url = match.group(1)
        
        # Check if already captured as markdown image
        already_captured = any(
            f.url == url and f.position.line_start == pos.line_start
            for f in results
        )
        if not already_captured:
            results.append(FigureArtifact(
                marker_type="image",
                identifier="",
                caption=None,
                url=url,
                file_path=None,
                position=pos
            ))
    
    # Image file paths
    for match in PATTERNS["figures"]["image_paths"].finditer(text):
        pos = create_position(text, match.start(), match.end())
        path = match.group(1)
        
        results.append(FigureArtifact(
            marker_type="image",
            identifier="",
            caption=None,
            url=None,
            file_path=path,
            position=pos
        ))
    
    # "see figure N" references
    references = []
    for match in PATTERNS["figures"]["see_figure_ref"].finditer(text):
        pos = create_position(text, match.start(), match.end())
        ref_type = match.group(1).lower()
        ref_id = match.group(2)
        references.append({
            "type": ref_type,
            "id": ref_id,
            "position": pos
        })
    
    # Attach references to nearest figure artifacts
    for ref in references:
        for artifact in results:
            if artifact.identifier == ref["id"]:
                artifact.references.append(f"line_{ref['position'].line_start}")
    
    return results


def extract_tables(text: str) -> list[FigureArtifact]:
    """Extract markdown tables and table markers."""
    results = []
    
    # Table markers [TABLE N]
    for match in PATTERNS["tables"]["table_marker"].finditer(text):
        pos = create_position(text, match.start(), match.end())
        identifier = match.group(1) or ""
        caption = match.group(2)
        
        results.append(FigureArtifact(
            marker_type="table",
            identifier=identifier,
            caption=caption.strip() if caption else None,
            url=None,
            file_path=None,
            position=pos
        ))
    
    # Markdown tables
    for match in PATTERNS["tables"]["markdown_table"].finditer(text):
        pos = create_position(text, match.start(), match.end())
        table_content = match.group(0)
        
        # Parse table data
        lines = table_content.strip().split('\n')
        table_data = []
        for line in lines:
            if re.match(r'^\|[-:| ]+\|$', line):
                continue  # Skip separator row
            cells = [cell.strip() for cell in line.split('|') if cell.strip()]
            if cells:
                table_data.append(cells)
        
        if table_data:
            results.append(FigureArtifact(
                marker_type="table",
                identifier="",
                caption=None,
                url=None,
                file_path=None,
                position=pos,
                table_data=table_data
            ))
    
    return results


def extract_section_headers(text: str) -> list[SectionHeader]:
    """Extract markdown section headers."""
    results = []
    
    for match in PATTERNS["pedagogy"]["headers"].finditer(text):
        level = len(match.group(1))
        title = match.group(2).strip()
        pos = create_position(text, match.start(), match.end())
        
        is_lo = bool(re.match(r'^(learning\s+objectives?|objectives?|goals?|outcomes?)', title, re.IGNORECASE))
        is_summary = bool(re.match(r'^summary', title, re.IGNORECASE))
        
        results.append(SectionHeader(
            level=level,
            title=title,
            position=pos,
            is_learning_objective=is_lo,
            is_summary=is_summary
        ))
    
    return results


def extract_learning_objectives(text: str) -> list[LearningObjective]:
    """Extract learning objectives sections and their bullets."""
    results = []
    
    # Find learning objectives sections
    for match in PATTERNS["pedagogy"]["learning_objectives"].finditer(text):
        section_text = match.group(0)
        section_pos = create_position(text, match.start(), match.end())
        
        # Extract header for context
        header_match = re.match(r'^(#{1,3})\s+(.+)$', section_text, re.MULTILINE)
        section_context = header_match.group(2) if header_match else None
        
        # Extract bullet points
        for bullet_match in PATTERNS["pedagogy"]["lo_bullets"].finditer(section_text):
            bullet_text = bullet_match.group(1).strip()
            rel_pos = create_position(section_text, bullet_match.start(), bullet_match.end())
            
            results.append(LearningObjective(
                text=bullet_text,
                position=Position(
                    line_start=section_pos.line_start + rel_pos.line_start - 1,
                    line_end=section_pos.line_start + rel_pos.line_end - 1
                ),
                section_context=section_context
            ))
    
    return results


def extract_key_takeaways(text: str) -> list[KeyTakeaway]:
    """Extract key takeaways sections."""
    results = []
    
    for match in PATTERNS["pedagogy"]["key_takeaway_marker"].finditer(text):
        section_text = match.group(0)
        section_pos = create_position(text, match.start(), match.end())
        
        # Try structured takeaway bullets first
        for bullet_match in PATTERNS["pedagogy"]["takeaway_bullets"].finditer(section_text):
            key = bullet_match.group(1).strip()
            description = bullet_match.group(2).strip()
            rel_pos = create_position(section_text, bullet_match.start(), bullet_match.end())
            
            results.append(KeyTakeaway(
                text=f"{key}: {description}",
                position=Position(
                    line_start=section_pos.line_start + rel_pos.line_start - 1,
                    line_end=section_pos.line_start + rel_pos.line_end - 1
                ),
                bullet_point=True
            ))
        
        # Fallback to regular bullets
        if not results:
            for bullet_match in PATTERNS["pedagogy"]["lo_bullets"].finditer(section_text):
                bullet_text = bullet_match.group(1).strip()
                rel_pos = create_position(section_text, bullet_match.start(), bullet_match.end())
                
                results.append(KeyTakeaway(
                    text=bullet_text,
                    position=Position(
                        line_start=section_pos.line_start + rel_pos.line_start - 1,
                        line_end=section_pos.line_start + rel_pos.line_end - 1
                    ),
                    bullet_point=True
                ))
    
    # Standalone **Remember:** markers
    for match in PATTERNS["pedagogy"]["remember_marker"].finditer(text):
        pos = create_position(text, match.start(), match.end())
        results.append(KeyTakeaway(
            text=match.group(1).strip(),
            position=pos,
            bullet_point=False
        ))
    
    return results


def extract_summaries(text: str) -> list[Summary]:
    """Extract summary sections."""
    results = []
    
    for match in PATTERNS["pedagogy"]["summary_marker"].finditer(text):
        section_text = match.group(0)
        pos = create_position(text, match.start(), match.end())
        
        # Check if it's bulleted
        is_bulleted = bool(re.search(r'^\s*[-*+]', section_text, re.MULTILINE))
        
        # Remove the header
        content = re.sub(r'^#{1,3}\s+Summary\s*\n', '', section_text, flags=re.IGNORECASE)
        
        results.append(Summary(
            text=content.strip(),
            position=pos,
            is_bulleted=is_bulleted
        ))
    
    return results


def extract_author_notes(text: str) -> list[AuthorNote]:
    """Extract author notes, tips, and important callouts."""
    results = []
    
    # Blockquotes
    for match in PATTERNS["author_notes"]["blockquote"].finditer(text):
        content = match.group(1).strip()
        pos = create_position(text, match.start(), match.end())
        
        # Check for note type in content
        note_type = "blockquote"
        if re.match(r'^(note|tip|info|warning)', content, re.IGNORECASE):
            note_type = "callout"
        
        results.append(AuthorNote(
            note_type=note_type,
            content=content,
            position=pos
        ))
    
    # Note: / Tip: markers
    for match in PATTERNS["author_notes"]["note_marker"].finditer(text):
        content = match.group(1).strip()
        pos = create_position(text, match.start(), match.end())
        
        results.append(AuthorNote(
            note_type="note",
            content=content,
            position=pos
        ))
    
    # Remember: / Important: markers
    for match in PATTERNS["author_notes"]["remember_important"].finditer(text):
        note_type = "important" if "important" in match.group(0).lower() else "remember"
        content = match.group(1).strip()
        pos = create_position(text, match.start(), match.end())
        
        results.append(AuthorNote(
            note_type=note_type,
            content=content,
            position=pos
        ))
    
    # Emoji markers
    for match in PATTERNS["author_notes"]["emoji_notes"].finditer(text):
        emoji = match.group(1)
        content = match.group(2).strip()
        pos = create_position(text, match.start(), match.end())
        
        note_type_map = {
            "💡": "tip",
            "📝": "note",
            "📌": "important",
            "⚠️": "warning",
            "❗": "warning",
            "ℹ️": "info",
            "✨": "highlight",
            "🎯": "goal",
        }
        
        results.append(AuthorNote(
            note_type=note_type_map.get(emoji, "note"),
            content=content,
            position=pos,
            emoji=emoji
        ))
    
    # Callout blocks > [!NOTE] style
    for match in PATTERNS["author_notes"]["callout_block"].finditer(text):
        note_type = match.group(1).lower()
        content = match.group(2).strip()
        pos = create_position(text, match.start(), match.end())
        
        results.append(AuthorNote(
            note_type=note_type,
            content=content,
            position=pos
        ))
    
    return results


def extract_difficulty_tags(text: str) -> list[DifficultyTag]:
    """Extract difficulty level indicators."""
    results = []
    
    # Explicit level markers
    level_map = {
        "beginner": DifficultyLevel.BEGINNER,
        "easy": DifficultyLevel.EASY,
        "medium": DifficultyLevel.MEDIUM,
        "intermediate": DifficultyLevel.INTERMEDIATE,
        "advanced": DifficultyLevel.ADVANCED,
        "hard": DifficultyLevel.HARD,
        "expert": DifficultyLevel.EXPERT,
    }
    
    for match in PATTERNS["difficulty"]["explicit_level"].finditer(text):
        level_str = match.group(1).lower()
        pos = create_position(text, match.start(), match.end())
        
        results.append(DifficultyTag(
            level=level_map.get(level_str, DifficultyLevel.MEDIUM),
            raw_text=match.group(0),
            position=pos,
            confidence=1.0
        ))
    
    # Numeric difficulty (e.g., Difficulty: 3/5)
    for match in PATTERNS["difficulty"]["explicit_numeric"].finditer(text):
        pos = create_position(text, match.start(), match.end())
        numerator = int(match.group(1))
        denominator = int(match.group(2)) if match.group(2) else 5
        
        # Map to difficulty level
        ratio = numerator / denominator
        if ratio <= 0.33:
            level = DifficultyLevel.EASY
        elif ratio <= 0.66:
            level = DifficultyLevel.MEDIUM
        else:
            level = DifficultyLevel.HARD
        
        results.append(DifficultyTag(
            level=level,
            raw_text=match.group(0),
            position=pos,
            confidence=1.0
        ))
    
    # Star ratings
    for match in PATTERNS["difficulty"]["star_rating"].finditer(text):
        pos = create_position(text, match.start(), match.end())
        stars = match.group(0)
        filled_count = stars.count('★')
        
        if filled_count <= 2:
            level = DifficultyLevel.EASY
        elif filled_count <= 3:
            level = DifficultyLevel.MEDIUM
        else:
            level = DifficultyLevel.HARD
        
        results.append(DifficultyTag(
            level=level,
            raw_text=stars,
            position=pos,
            star_count=filled_count,
            confidence=0.9
        ))
    
    # Implicit markers - with lower confidence
    for match in PATTERNS["difficulty"]["implicit_beginner"].finditer(text):
        pos = create_position(text, match.start(), match.end())
        results.append(DifficultyTag(
            level=DifficultyLevel.BEGINNER,
            raw_text=match.group(0),
            position=pos,
            confidence=0.6
        ))
    
    for match in PATTERNS["difficulty"]["implicit_intermediate"].finditer(text):
        pos = create_position(text, match.start(), match.end())
        results.append(DifficultyTag(
            level=DifficultyLevel.INTERMEDIATE,
            raw_text=match.group(0),
            position=pos,
            confidence=0.6
        ))
    
    for match in PATTERNS["difficulty"]["implicit_advanced"].finditer(text):
        pos = create_position(text, match.start(), match.end())
        results.append(DifficultyTag(
            level=DifficultyLevel.ADVANCED,
            raw_text=match.group(0),
            position=pos,
            confidence=0.6
        ))
    
    return results


def extract_traps_and_mistakes(text: str) -> list[TrapOrMistake]:
    """Extract common mistakes, traps, and pitfalls."""
    results = []
    
    # Explicit trap markers
    for match in PATTERNS["traps"]["explicit_trap"].finditer(text):
        content = match.group(1).strip()
        pos = create_position(text, match.start(), match.end())
        marker = "explicit"
        
        severity = "warning"
        if re.search(r'\b(critical|severe|major)\b', content, re.IGNORECASE):
            severity = "critical"
        elif re.search(r'\b(minor|small|typo)\b', content, re.IGNORECASE):
            severity = "info"
        
        results.append(TrapOrMistake(
            marker=marker,
            content=content,
            position=pos,
            severity=severity
        ))
    
    # "Students often..." warnings
    for match in PATTERNS["traps"]["students_often"].finditer(text):
        content = match.group(1).strip()
        pos = create_position(text, match.start(), match.end())
        
        results.append(TrapOrMistake(
            marker="students_often",
            content=content,
            position=pos,
            severity="warning"
        ))
    
    # Warning emojis
    for match in PATTERNS["traps"]["warning_emoji"].finditer(text):
        emoji = match.group(1)
        content = match.group(2).strip()
        pos = create_position(text, match.start(), match.end())
        
        severity = "warning"
        if emoji in ["🚨", "⛔"]:
            severity = "critical"
        
        results.append(TrapOrMistake(
            marker="emoji",
            content=content,
            position=pos,
            severity=severity,
            emoji=emoji
        ))
    
    # Anti-pattern markers
    for match in PATTERNS["traps"]["antipattern"].finditer(text):
        content = match.group(1).strip()
        pos = create_position(text, match.start(), match.end())
        
        results.append(TrapOrMistake(
            marker="antipattern",
            content=content,
            position=pos,
            severity="warning"
        ))
    
    # "Be careful" / "Watch out"
    for match in PATTERNS["traps"]["careful_marker"].finditer(text):
        content = match.group(1).strip()
        pos = create_position(text, match.start(), match.end())
        
        results.append(TrapOrMistake(
            marker="careful",
            content=content,
            position=pos,
            severity="warning"
        ))
    
    return results


# =============================================================================
# MASTER EXTRACTION FUNCTION
# =============================================================================

@dataclass
class ExtractionResult:
    figures: list[FigureArtifact]
    tables: list[FigureArtifact]
    sections: list[SectionHeader]
    learning_objectives: list[LearningObjective]
    key_takeaways: list[KeyTakeaway]
    summaries: list[Summary]
    author_notes: list[AuthorNote]
    difficulty_tags: list[DifficultyTag]
    traps_mistakes: list[TrapOrMistake]


def extract_all(text: str) -> ExtractionResult:
    """Run all extraction patterns on the text."""
    return ExtractionResult(
        figures=extract_figures_and_charts(text),
        tables=extract_tables(text),
        sections=extract_section_headers(text),
        learning_objectives=extract_learning_objectives(text),
        key_takeaways=extract_key_takeaways(text),
        summaries=extract_summaries(text),
        author_notes=extract_author_notes(text),
        difficulty_tags=extract_difficulty_tags(text),
        traps_mistakes=extract_traps_and_mistakes(text),
    )


# =============================================================================
# ONTOLOGY EXPORT FUNCTIONS
# =============================================================================

def to_dict(obj) -> dict:
    """Convert dataclass to dictionary for serialization."""
    if hasattr(obj, '__dataclass_fields__'):
        result = {}
        for field_name in obj.__dataclass_fields__:
            value = getattr(obj, field_name)
            result[field_name] = to_dict(value)
        return result
    elif isinstance(obj, list):
        return [to_dict(item) for item in obj]
    elif isinstance(obj, Enum):
        return obj.value
    else:
        return obj


def export_for_ontology(result: ExtractionResult) -> dict:
    """Export extraction result in ontology-compatible format."""
    return {
        "artifacts": {
            "figures": [to_dict(f) for f in result.figures],
            "tables": [to_dict(t) for t in result.tables],
        },
        "pedagogy": {
            "sections": [to_dict(s) for s in result.sections],
            "learning_objectives": [to_dict(lo) for lo in result.learning_objectives],
            "key_takeaways": [to_dict(kt) for kt in result.key_takeaways],
            "summaries": [to_dict(s) for s in result.summaries],
        },
        "metadata": {
            "author_notes": [to_dict(n) for n in result.author_notes],
            "difficulty_tags": [to_dict(d) for d in result.difficulty_tags],
            "traps_mistakes": [to_dict(t) for t in result.traps_mistakes],
        },
    }


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

if __name__ == "__main__":
    sample_text = """
# Learning Objectives

By the end of this chapter, you will:
- Understand the basics of Python
- Apply design patterns in practice
- Avoid common pitfalls

## Figure 1: System Architecture

![Architecture Diagram](https://example.com/images/arch.png)

[FIGURE 2: Data Flow Diagram]

**Difficulty: Medium**

> **Note:** This is an important concept to remember.

💡 Tip: Always validate user input!

⚠️ Common mistake: Forgetting to close file handles.

Students often struggle with recursion depth limits.

★★★ (3/5 difficulty)

## Key Takeaways

- **Pattern Matching**: Use regex for text extraction
- **Validation**: Always sanitize inputs

## Summary

This chapter covered the fundamentals.
"""

    result = extract_all(sample_text)
    
    print("=== FIGURES ===")
    for f in result.figures:
        print(f"  {f.marker_type}: {f.identifier or 'N/A'} - {f.caption or 'N/A'}")
    
    print("\n=== SECTIONS ===")
    for s in result.sections:
        print(f"  {'#' * s.level} {s.title}")
    
    print("\n=== LEARNING OBJECTIVES ===")
    for lo in result.learning_objectives:
        print(f"  - {lo.text}")
    
    print("\n=== DIFFICULTY ===")
    for d in result.difficulty_tags:
        print(f"  {d.level.value}: {d.raw_text.strip()} (confidence: {d.confidence})")
    
    print("\n=== TRAPS ===")
    for t in result.traps_mistakes:
        print(f"  [{t.severity}] {t.content[:50]}...")
    
    print("\n=== ONTOLOGY EXPORT (JSON) ===")
    import json
    print(json.dumps(export_for_ontology(result), indent=2))