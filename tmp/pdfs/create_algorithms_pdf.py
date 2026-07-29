from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "output" / "pdf" / "Frequency_Analyzer_Algorithms_Explained.pdf"

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN_X = 21 * mm
MARGIN_TOP = 18 * mm
MARGIN_BOTTOM = 18 * mm
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN_X

INK = colors.HexColor("#1D2733")
MUTED = colors.HexColor("#52606D")
BLUE = colors.HexColor("#245B78")
PALE_BLUE = colors.HexColor("#EEF5F8")
PALE_GREY = colors.HexColor("#F4F6F7")
LINE = colors.HexColor("#CCD5DB")
WHITE = colors.white


styles = getSampleStyleSheet()
styles.add(
    ParagraphStyle(
        name="ReportTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=24,
        leading=29,
        textColor=INK,
        alignment=TA_LEFT,
        spaceAfter=7 * mm,
    )
)
styles.add(
    ParagraphStyle(
        name="ReportSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=12,
        leading=17,
        textColor=MUTED,
        spaceAfter=7 * mm,
    )
)
styles.add(
    ParagraphStyle(
        name="Section",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=17,
        leading=21,
        textColor=INK,
        spaceBefore=2 * mm,
        spaceAfter=4 * mm,
        keepWithNext=True,
    )
)
styles.add(
    ParagraphStyle(
        name="Subsection",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11.5,
        leading=15,
        textColor=BLUE,
        spaceBefore=3 * mm,
        spaceAfter=1.5 * mm,
        keepWithNext=True,
    )
)
styles.add(
    ParagraphStyle(
        name="BodyText2",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9.6,
        leading=14,
        textColor=INK,
        spaceAfter=2.4 * mm,
        alignment=TA_LEFT,
    )
)
styles.add(
    ParagraphStyle(
        name="Small",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8.2,
        leading=11,
        textColor=MUTED,
        spaceAfter=1.5 * mm,
    )
)
styles.add(
    ParagraphStyle(
        name="Callout",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9.4,
        leading=13.5,
        textColor=INK,
        leftIndent=4 * mm,
        rightIndent=4 * mm,
        spaceBefore=1.5 * mm,
        spaceAfter=1.5 * mm,
    )
)
styles.add(
    ParagraphStyle(
        name="DiagramText",
        parent=styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=7.8,
        leading=9.5,
        textColor=INK,
        alignment=TA_CENTER,
    )
)
styles.add(
    ParagraphStyle(
        name="TableHead",
        parent=styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        textColor=WHITE,
    )
)
styles.add(
    ParagraphStyle(
        name="TableCell",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8.3,
        leading=11,
        textColor=INK,
    )
)


def P(text: str, style: str = "BodyText2") -> Paragraph:
    return Paragraph(text, styles[style])


def bullets(items: list[str], level: int = 0) -> ListFlowable:
    return ListFlowable(
        [ListItem(P(item), leftIndent=0) for item in items],
        bulletType="bullet",
        start="circle",
        leftIndent=(7 + 5 * level) * mm,
        bulletFontName="Helvetica",
        bulletFontSize=6,
        bulletColor=BLUE,
        spaceAfter=2 * mm,
    )


def callout(label: str, text: str) -> Table:
    content = P(f"<b>{label}:</b> {text}", "Callout")
    table = Table([[content]], colWidths=[CONTENT_WIDTH])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALE_BLUE),
                ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 * mm),
            ]
        )
    )
    return table


class BlockDiagram(Flowable):
    def __init__(
        self,
        labels: list[str],
        width: float = CONTENT_WIDTH,
        box_height: float = 16 * mm,
        gap: float = 7 * mm,
        caption: str | None = None,
    ):
        super().__init__()
        self.labels = labels
        self.width = width
        self.box_height = box_height
        self.gap = gap
        self.caption = caption
        self.caption_height = 8 * mm if caption else 0
        self.height = box_height + self.caption_height

    def draw(self):
        canvas = self.canv
        count = len(self.labels)
        box_width = (self.width - self.gap * (count - 1)) / count
        y = self.caption_height
        for index, label in enumerate(self.labels):
            x = index * (box_width + self.gap)
            canvas.setFillColor(PALE_BLUE if index % 2 == 0 else PALE_GREY)
            canvas.setStrokeColor(BLUE)
            canvas.setLineWidth(0.8)
            canvas.roundRect(x, y, box_width, self.box_height, 2.5 * mm, fill=1)

            paragraph = Paragraph(label, styles["DiagramText"])
            _, paragraph_height = paragraph.wrap(
                box_width - 4 * mm, self.box_height - 3 * mm
            )
            paragraph.drawOn(
                canvas,
                x + 2 * mm,
                y + (self.box_height - paragraph_height) / 2,
            )

            if index < count - 1:
                arrow_start = x + box_width + 1 * mm
                arrow_end = x + box_width + self.gap - 1 * mm
                arrow_y = y + self.box_height / 2
                canvas.setStrokeColor(MUTED)
                canvas.setFillColor(MUTED)
                canvas.line(arrow_start, arrow_y, arrow_end, arrow_y)
                canvas.line(
                    arrow_end,
                    arrow_y,
                    arrow_end - 2 * mm,
                    arrow_y + 1.3 * mm,
                )
                canvas.line(
                    arrow_end,
                    arrow_y,
                    arrow_end - 2 * mm,
                    arrow_y - 1.3 * mm,
                )

        if self.caption:
            canvas.setFillColor(MUTED)
            canvas.setFont("Helvetica-Oblique", 7.5)
            caption_width = stringWidth(
                self.caption, "Helvetica-Oblique", 7.5
            )
            canvas.drawString(
                max(0, (self.width - caption_width) / 2),
                1.5 * mm,
                self.caption,
            )


class ThresholdDiagram(Flowable):
    def __init__(self, width: float = CONTENT_WIDTH, height: float = 50 * mm):
        super().__init__()
        self.width = width
        self.height = height

    def draw(self):
        c = self.canv
        left = 13 * mm
        right = self.width - 4 * mm
        bottom = 7 * mm
        top = self.height - 5 * mm

        c.setStrokeColor(LINE)
        c.setLineWidth(0.7)
        c.line(left, bottom, left, top)
        c.line(left, bottom, right, bottom)
        c.setFont("Helvetica", 7)
        c.setFillColor(MUTED)
        c.drawString(0, top - 1 * mm, "Power")
        c.drawRightString(right, 1.5 * mm, "Frequency")

        noise_y = bottom + 8 * mm
        exit_y = bottom + 16 * mm
        enter_y = bottom + 28 * mm
        for y, label, color in (
            (noise_y, "Estimated noise floor", MUTED),
            (exit_y, "Exit threshold", colors.HexColor("#B06A00")),
            (enter_y, "Enter threshold", BLUE),
        ):
            c.setStrokeColor(color)
            c.setDash(3, 2)
            c.line(left, y, right, y)
            c.setDash()
            c.setFillColor(color)
            c.setFont("Helvetica", 7)
            c.drawString(left + 1 * mm, y + 1.2 * mm, label)

        points = [
            (left, noise_y + 0.5 * mm),
            (left + 16 * mm, noise_y - 1 * mm),
            (left + 29 * mm, noise_y + 1.5 * mm),
            (left + 39 * mm, exit_y + 1 * mm),
            (left + 47 * mm, enter_y + 4 * mm),
            (left + 76 * mm, enter_y + 5 * mm),
            (left + 85 * mm, exit_y + 1 * mm),
            (left + 99 * mm, noise_y),
            (right, noise_y + 1 * mm),
        ]
        c.setStrokeColor(INK)
        c.setLineWidth(1.6)
        path = c.beginPath()
        path.moveTo(*points[0])
        for x, y in points[1:]:
            path.lineTo(x, y)
        c.drawPath(path)

        c.setFillColor(PALE_BLUE)
        c.setStrokeColor(BLUE)
        c.roundRect(
            left + 39 * mm,
            bottom + 2 * mm,
            46 * mm,
            4.5 * mm,
            1.5 * mm,
            fill=1,
        )
        c.setFillColor(BLUE)
        c.setFont("Helvetica-Bold", 7)
        c.drawCentredString(
            left + 62 * mm, bottom + 3.3 * mm, "Detected carrier region"
        )


class PercentPowerDiagram(Flowable):
    def __init__(self, width: float = CONTENT_WIDTH, height: float = 41 * mm):
        super().__init__()
        self.width = width
        self.height = height

    def draw(self):
        c = self.canv
        left = 14 * mm
        right = self.width - 5 * mm
        bottom = 8 * mm
        top = self.height - 5 * mm
        c.setStrokeColor(LINE)
        c.line(left, bottom, left, top)
        c.line(left, bottom, right, bottom)
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 7)
        c.drawString(0, top - 1 * mm, "Power")
        c.drawRightString(right, 1.5 * mm, "Frequency")

        span = right - left
        curve = [
            (left, bottom + 1 * mm),
            (left + 0.18 * span, bottom + 3 * mm),
            (left + 0.34 * span, bottom + 12 * mm),
            (left + 0.43 * span, top - 1 * mm),
            (left + 0.58 * span, top - 3 * mm),
            (left + 0.69 * span, bottom + 11 * mm),
            (left + 0.82 * span, bottom + 3 * mm),
            (right, bottom + 1 * mm),
        ]
        path = c.beginPath()
        path.moveTo(*curve[0])
        for x, y in curve[1:]:
            path.lineTo(x, y)
        path.lineTo(right, bottom)
        path.lineTo(left, bottom)
        path.close()
        c.setFillColor(PALE_BLUE)
        c.setStrokeColor(BLUE)
        c.drawPath(path, fill=1, stroke=1)

        low_x = left + 0.24 * span
        high_x = left + 0.78 * span
        c.setStrokeColor(colors.HexColor("#B06A00"))
        c.setDash(3, 2)
        c.line(low_x, bottom, low_x, top)
        c.line(high_x, bottom, high_x, top)
        c.setDash()
        c.setFillColor(colors.HexColor("#B06A00"))
        c.setFont("Helvetica-Bold", 7)
        c.drawCentredString(low_x, top + 1 * mm, "0.5%")
        c.drawCentredString(high_x, top + 1 * mm, "99.5%")
        c.setFillColor(INK)
        c.drawCentredString(
            (low_x + high_x) / 2, bottom + 2 * mm, "Occupied bandwidth"
        )


def section_header(number: str, title: str, file_name: str) -> list:
    return [
        P(f"{number}. {title}", "Section"),
        P(f"<b>Implementation:</b> {file_name}", "Small"),
    ]


def algorithm_summary(
    what: str,
    why: str,
    significance: str,
) -> Table:
    data = [
        [P("WHAT IT FINDS", "TableHead"), P("WHY WE USE IT", "TableHead")],
        [P(what, "TableCell"), P(why, "TableCell")],
        [P("SIGNIFICANCE", "TableHead"), ""],
        [P(significance, "TableCell"), ""],
    ]
    table = Table(data, colWidths=[CONTENT_WIDTH / 2, CONTENT_WIDTH / 2])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BLUE),
                ("BACKGROUND", (0, 2), (-1, 2), BLUE),
                ("SPAN", (0, 2), (1, 2)),
                ("SPAN", (0, 3), (1, 3)),
                ("BACKGROUND", (0, 1), (-1, 1), PALE_GREY),
                ("BACKGROUND", (0, 3), (-1, 3), PALE_GREY),
                ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                ("INNERGRID", (0, 0), (-1, 1), 0.4, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 2.5 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2.5 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 1.7 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.7 * mm),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def page_decor(canvas, doc):
    canvas.saveState()
    page = canvas.getPageNumber()
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN_X, 13 * mm, PAGE_WIDTH - MARGIN_X, 13 * mm)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(
        MARGIN_X, 8.5 * mm, "Frequency Analyzer - Algorithms Explained"
    )
    canvas.drawRightString(PAGE_WIDTH - MARGIN_X, 8.5 * mm, f"Page {page}")
    canvas.restoreState()


story: list = []

# Cover and purpose
story.extend(
    [
        Spacer(1, 12 * mm),
        P("Frequency Analyzer Algorithms Explained", "ReportTitle"),
        P(
            "A plain-language guide to what each algorithm finds, how it works, "
            "why it is used, and why its result matters.",
            "ReportSubtitle",
        ),
        callout(
            "Who this is for",
            "A reader who has not seen this project before and may not have a "
            "background in software-defined radio or digital signal processing.",
        ),
        Spacer(1, 7 * mm),
        P("The project in one paragraph", "Subsection"),
        P(
            "The application receives complex in-phase and quadrature samples, "
            "usually called IQ samples, from an SDR. Those samples describe a "
            "radio signal as it changes over time. The software converts the "
            "samples into a spectrum, where the horizontal axis is frequency and "
            "the vertical axis is signal level. It then searches that spectrum "
            "for carriers and peaks, measures bandwidth and power, maintains "
            "historical traces, applies calibration, and places markers on useful "
            "points.",
        ),
        Spacer(1, 4 * mm),
        P("Algorithms covered", "Subsection"),
        bullets(
            [
                "Spectrum estimation using a Hann-windowed FFT.",
                "Adaptive carrier-band detection.",
                "Detection of multiple distinct spectral peaks.",
                "Sub-bin estimation of the strongest signal frequency.",
                "Noise-floor estimation.",
                "Occupied-bandwidth measurement.",
                "Channel-power integration.",
                "Maximum hold, minimum hold, and power averaging.",
                "Power calibration from dBFS to dBm.",
                "HackRF frequency-axis correction.",
                "Automatic peak tracking and marker peak search.",
            ]
        ),
        Spacer(1, 5 * mm),
        P(
            "The explanations describe the current implementation in the source "
            "code. They intentionally avoid features that are only ordinary user "
            "interface operations, such as snapping a marker to the nearest bin.",
            "Small",
        ),
        PageBreak(),
    ]
)

# Foundation and pipeline
story.extend(
    [
        P("Before the algorithms: four simple ideas", "Section"),
        P("<b>1. IQ samples are time-domain measurements.</b>"),
        P(
            "An SDR does not directly hand the program a list of radio stations. "
            "It supplies a stream of numerical samples. Each sample contains "
            "magnitude and phase information for the received radio waveform."
        ),
        P("<b>2. A spectrum is a frequency-domain view.</b>"),
        P(
            "The spectrum reorganizes the same information by frequency. A strong "
            "tone appears as a peak. A digitally modulated transmission usually "
            "appears as a wider raised band."
        ),
        P("<b>3. An FFT bin is one small frequency slot.</b>"),
        P(
            "The 4096-point FFT divides the sampled bandwidth into 4096 slots. "
            "Each slot has a center frequency and a measured level. The approximate "
            "bin spacing, also reported as resolution bandwidth, is sample rate "
            "divided by 4096."
        ),
        P("<b>4. dBFS and dBm are different.</b>"),
        P(
            "dBFS says how large a digital sample is compared with the ADC's full "
            "scale. dBm describes physical RF power relative to one milliwatt. "
            "The program can only report dBm when a valid device calibration is "
            "available."
        ),
        Spacer(1, 4 * mm),
        P("Overall processing flow", "Subsection"),
        BlockDiagram(
            [
                "SDR<br/>IQ samples",
                "FFT<br/>spectrum",
                "Traces and<br/>calibration",
                "Detection and<br/>measurements",
                "Display and<br/>markers",
            ],
            caption="Each stage adds information while preserving the original raw dBFS trace.",
        ),
        Spacer(1, 5 * mm),
        callout(
            "Important distinction",
            "Carrier detection, multi-peak detection, and the measurement panel "
            "do related jobs, but they are not duplicates. A carrier is a whole "
            "occupied frequency band. A peak is one locally high point. A "
            "measurement is a single numerical summary of the current spectrum.",
        ),
        PageBreak(),
    ]
)

# FFT
story.extend(section_header("1", "Spectrum estimation with a Hann-windowed FFT", "backend/dsp.py"))
story.extend(
    [
        algorithm_summary(
            "The frequencies present in the incoming IQ block and the relative "
            "level of each frequency.",
            "The SDR supplies time-domain samples, while a spectrum analyzer must "
            "show frequency-domain information.",
            "Every detector and measurement in the application depends on this "
            "spectrum. If the spectrum is inaccurate or unstable, all later "
            "results will also be inaccurate.",
        ),
        P("How it works, step by step", "Subsection"),
        BlockDiagram(
            [
                "Remove sample<br/>mean",
                "Apply Hann<br/>window",
                "Compute<br/>4096-point FFT",
                "Normalize and<br/>convert to dBFS",
                "Build frequency<br/>axis",
            ]
        ),
        Spacer(1, 3 * mm),
        bullets(
            [
                "<b>Remove the mean:</b> The average value of the IQ block is "
                "subtracted. This acts as a simple DC blocker and reduces a false "
                "spike at the exact center of the display.",
                "<b>Apply a Hann window:</b> The block is gently reduced toward "
                "zero at both ends. This prevents the sudden block boundaries from "
                "spreading one signal into many neighboring frequency bins.",
                "<b>Compute the FFT:</b> The Fast Fourier Transform separates the "
                "time-domain samples into frequency bins.",
                "<b>Shift the result:</b> The negative-frequency half is moved to "
                "the left and the positive-frequency half to the right, placing "
                "the receiver's center frequency in the middle.",
                "<b>Normalize:</b> The FFT magnitude is divided by the Hann "
                "window's coherent gain so that the displayed level of a tone is "
                "not reduced merely because a window was used.",
                "<b>Convert to dBFS:</b> The linear magnitude becomes "
                "20 log10(magnitude). Values below the numerical floor are clamped "
                "to -140 dBFS so logarithms remain finite.",
                "<b>Crop the displayed span:</b> If the requested display span is "
                "smaller than the sample rate, bins outside the requested range "
                "are removed.",
            ]
        ),
        P("Simple example", "Subsection"),
        P(
            "Imagine that the receiver contains one pure tone 125 kHz above its "
            "center frequency. The FFT places most of that tone's energy near the "
            "bin whose frequency is center + 125 kHz. The Hann window keeps the "
            "tone from appearing as a wide artificial smear."
        ),
        callout(
            "Why the Hann window matters",
            "Real signals do not normally start and stop exactly at the boundaries "
            "of a 4096-sample block. Without windowing, the artificial jump between "
            "the last and first sample creates spectral leakage that can hide weak "
            "nearby signals or create misleading shoulders.",
        ),
        PageBreak(),
    ]
)

# Carrier detector part 1
story.extend(section_header("2", "Adaptive carrier-band detection", "backend/carrier_detection.py"))
story.extend(
    [
        algorithm_summary(
            "Sustained occupied frequency bands, including their left edge, right "
            "edge, center bin, strongest bin, peak level, noise estimate, and a "
            "confidence value.",
            "A wide modulated transmission is not well described by one peak. We "
            "need to identify the complete occupied region while rejecting random "
            "noise spikes and receiver passband artifacts.",
            "This algorithm lets the application count carriers and draw overlays "
            "that align with actual band edges. It is the main signal-presence "
            "decision algorithm in the project.",
        ),
        P("Core idea: use two thresholds instead of one", "Subsection"),
        P(
            "A single threshold causes unstable edges. A slightly noisy point may "
            "make a band repeatedly appear, disappear, or change width. The "
            "detector therefore uses a high threshold to prove that a real carrier "
            "exists and a lower threshold to follow that carrier out to its weaker "
            "edges. This is called hysteresis."
        ),
        ThresholdDiagram(),
        P(
            "The high line is the <b>enter threshold</b>. A carrier must contain a "
            "long, strong core above it. The lower line is the <b>exit threshold</b>. "
            "Once a strong core exists, the region can extend down to this lower "
            "line so that the rising and falling shoulders are retained."
        ),
        P("Step 1: smooth the trace", "Subsection"),
        P(
            "A short moving average reduces bin-to-bin fluctuations. The default "
            "window adapts to the number of displayed bins and is kept odd so it "
            "has a clear center. Edge padding repeats the end values instead of "
            "inserting zero dB, because zero-padding a negative-dB spectrum would "
            "manufacture very large false edge peaks."
        ),
        P("Step 2: estimate the background robustly", "Subsection"),
        P(
            "The detector first finds the 60th percentile of the smoothed trace "
            "and keeps values at or below it. The median of those lower values "
            "becomes the background noise estimate. Strong occupied bins are "
            "therefore prevented from pulling the estimated floor upward."
        ),
        PageBreak(),
    ]
)

# Carrier detector part 2
story.extend(
    [
        P("2. Adaptive carrier-band detection - decision process", "Section"),
        P("Step 3: measure how rough the noise is", "Subsection"),
        P(
            "The detector looks at the change between neighboring smoothed bins. "
            "It uses the median absolute deviation, or MAD, of those changes to "
            "estimate random floor variation. MAD is used because it is less "
            "sensitive to a few extreme values than standard deviation."
        ),
        P("Step 4: create adaptive thresholds", "Subsection"),
        bullets(
            [
                "Enter level = noise floor + the larger of 10 dB or 6 times the "
                "estimated noise variation.",
                "Exit level = noise floor + the larger of 3 dB or 3 times the "
                "estimated noise variation.",
            ]
        ),
        P(
            "On a clean receiver, the configured 10 dB and 3 dB margins dominate. "
            "On a rough receiver, the variation-based terms raise the thresholds "
            "automatically and reduce false detections."
        ),
        P("Step 5: require a sustained strong core", "Subsection"),
        P(
            "The algorithm finds consecutive runs above the lower threshold. "
            "Inside each run it requires at least 50 consecutive smoothed bins "
            "above the high threshold. A single narrow spike therefore cannot "
            "become a carrier."
        ),
        P("Step 6: reject incomplete edge regions", "Subsection"),
        P(
            "A region touching the first or last FFT bin is rejected. The detector "
            "cannot see background on both sides of such a region, so it cannot "
            "reliably claim that both band edges were measured. This also removes "
            "many passband-edge artifacts."
        ),
        P("Step 7: refine the edges on unsmoothed data", "Subsection"),
        P(
            "Smoothing is useful for making the decision but can shift an edge. "
            "The detector therefore returns to the original unsmoothed spectrum. "
            "A valid edge needs three consecutive bins above the exit level. This "
            "keeps one noisy bin from pulling the boundary outward."
        ),
        P("Step 8: describe the result", "Subsection"),
        bullets(
            [
                "The peak bin is the strongest original bin inside the detected region.",
                "The center bin is halfway between the two measured edges. It is "
                "the geometric center of the region, not necessarily the peak.",
                "Confidence describes how far the peak rises above the enter "
                "threshold and is limited to the range 0 to 1.",
                "Nearby regions can optionally be merged when their gap is below a "
                "configured number of bins. The current default does not merge gaps.",
            ]
        ),
        callout(
            "Significance",
            "This combination of robust noise estimation, hysteresis, run-length "
            "qualification, and unsmoothed edge refinement is designed to keep "
            "broad low-prominence noise humps from being labeled as carriers while "
            "preserving the beginning and end of a real digital transmission.",
        ),
        PageBreak(),
    ]
)

# Peak engine
story.extend(section_header("3", "Detection of multiple distinct peaks", "backend/peak.py"))
story.extend(
    [
        algorithm_summary(
            "Up to ten strong, separate local peaks in the current live spectrum.",
            "Several transmissions may be visible at once. Simply taking the "
            "largest bin would report only one of them, while returning every "
            "small bump would mostly report noise or several points from the same "
            "signal.",
            "The peak list gives a compact set of notable signals for measurement "
            "and display without filling the result with closely spaced duplicates.",
        ),
        P("How it works", "Subsection"),
        BlockDiagram(
            [
                "Median + 6 dB<br/>threshold",
                "Find local<br/>maxima",
                "Sort strongest<br/>first",
                "Apply spacing<br/>guard",
                "Keep up to<br/>10 peaks",
            ]
        ),
        Spacer(1, 3 * mm),
        bullets(
            [
                "<b>Adaptive threshold:</b> The median amplitude of the live "
                "spectrum is calculated, and 6 dB is added. The median makes the "
                "threshold follow the current displayed floor.",
                "<b>Local maximum test:</b> A candidate must be higher than the bin "
                "on its left, at least as high as the bin on its right, and above "
                "the threshold.",
                "<b>Ranking:</b> Candidates are sorted from strongest to weakest.",
                "<b>Guard spacing:</b> After one peak is accepted, another "
                "candidate is rejected if it is closer than roughly 1 percent of "
                "the displayed bin count. The guard is never smaller than three bins.",
                "<b>Limit:</b> Processing stops after ten peaks have been accepted.",
            ]
        ),
        P("Simple example", "Subsection"),
        P(
            "Suppose one transmitter creates a cluster of five high bins and a "
            "second transmitter creates another cluster farther away. The local "
            "maximum test finds the tops of both clusters. The spacing guard keeps "
            "only one representative from each cluster, so the result is two "
            "useful peaks rather than ten almost identical entries."
        ),
        callout(
            "Difference from carrier detection",
            "A peak is a point. A carrier is a region. A wide flat-topped carrier "
            "may have several small local maxima, but carrier detection should "
            "still return one occupied band.",
        ),
        PageBreak(),
    ]
)

# Measurements peak/noise
story.extend(section_header("4", "Strongest-frequency estimation with sub-bin interpolation", "backend/measurements.py"))
story.extend(
    [
        algorithm_summary(
            "The frequency of the strongest live signal with a result that can "
            "fall between FFT-bin centers.",
            "A plain maximum search is limited to the fixed bin grid. The true "
            "signal can lie between two bins, making the reported frequency jump "
            "in whole-bin steps.",
            "Parabolic interpolation provides a smoother and usually more accurate "
            "peak-frequency readout without increasing the FFT size or processing "
            "another sample block.",
        ),
        P("How it works", "Subsection"),
        bullets(
            [
                "Find the strongest amplitude bin.",
                "Read that bin and its immediate left and right neighbors.",
                "Fit the top of a parabola through those three logarithmic "
                "amplitude values.",
                "Use the parabola's vertex to estimate how far the real peak lies "
                "from the center bin.",
                "Multiply that fractional-bin shift by the bin spacing and add it "
                "to the center-bin frequency.",
            ]
        ),
        P(
            "If the strongest bin is at an array edge, the three points form a "
            "flat or unusable curve, or the calculated shift is unreasonable, the "
            "algorithm safely returns the original bin frequency."
        ),
        P("Simple example", "Subsection"),
        P(
            "With 488 Hz bin spacing, the strongest bin might be centered at "
            "100.125000 MHz. If its two neighbors suggest that the peak is "
            "0.3 bins to the right, the estimated frequency becomes approximately "
            "100.125146 MHz instead of being forced to the bin center."
        ),
        Spacer(1, 5 * mm),
        P("5. Displayed noise-floor estimation", "Section"),
        P("<b>Implementation:</b> backend/measurements.py", "Small"),
        algorithm_summary(
            "A representative per-bin background level across the displayed span.",
            "The average can be pulled upward by strong transmissions. The median "
            "stays representative as long as less than about half of the displayed "
            "bins are dominated by signals.",
            "The result gives the reader a simple indication of receiver background "
            "and signal visibility. It also provides context for interpreting peak "
            "height.",
        ),
        P("How it works", "Subsection"),
        P(
            "All displayed live-spectrum amplitudes are sorted conceptually, and "
            "the middle value is used. In practice NumPy computes the median "
            "directly. This is intentionally simple and robust."
        ),
        callout(
            "Do not confuse the two noise estimates",
            "The measurement panel uses the median of all displayed bins. Carrier "
            "detection uses a more conservative lower-60-percent median plus a "
            "MAD-based roughness estimate because it must make detection decisions.",
        ),
        PageBreak(),
    ]
)

# OBW and channel
story.extend(section_header("6", "Occupied-bandwidth measurement", "backend/measurements.py"))
story.extend(
    [
        algorithm_summary(
            "The frequency interval containing the middle 99 percent of all "
            "displayed spectral power.",
            "A signal's width should be based on its distributed power rather than "
            "on one arbitrary amplitude threshold.",
            "Occupied bandwidth summarizes how much spectrum the received energy "
            "uses and is a standard way to describe modulated signals.",
        ),
        PercentPowerDiagram(),
        P("How it works", "Subsection"),
        bullets(
            [
                "Convert each logarithmic bin value back to linear power using "
                "10 raised to amplitude divided by 10.",
                "Add the linear powers to obtain total displayed power.",
                "Build a cumulative sum from the lowest displayed frequency to the highest.",
                "Find the first bin where cumulative power reaches 0.5 percent of the total.",
                "Find the first bin where cumulative power reaches 99.5 percent.",
                "Subtract the lower frequency from the upper frequency.",
            ]
        ),
        P("Why 0.5 percent and 99.5 percent?", "Subsection"),
        P(
            "Removing 0.5 percent from each tail leaves the middle 99 percent. "
            "Very small distant components therefore have less influence than they "
            "would in a simple first-nonzero-to-last-nonzero width."
        ),
        callout(
            "Interpretation limit",
            "The current implementation uses every displayed bin, including noise "
            "and unrelated transmissions. A weak signal in a wide span can "
            "therefore produce a large occupied-bandwidth value. It is not yet a "
            "measurement restricted to one detected carrier region.",
        ),
        PageBreak(),
        P("7. Channel-power integration", "Section"),
        P("<b>Implementation:</b> backend/measurements.py", "Small"),
        algorithm_summary(
            "The sum of linear power across the complete displayed span.",
            "Decibel values cannot be added directly. Each bin must first be "
            "converted to linear power.",
            "This gives one total-power number for the displayed channel or span. "
            "When calibration is valid, the result is presented as calibrated dBm.",
        ),
        P(
            "The same linear powers used for occupied bandwidth are summed. The "
            "result is converted back with 10 log10(total power). A very small "
            "positive floor prevents the logarithm of zero."
        ),
        callout(
            "Current scope",
            "The algorithm integrates the complete displayed span. It does not "
            "currently use detected carrier edges as channel boundaries.",
        ),
    ]
)

# Traces
story.extend(section_header("8", "Maximum hold, minimum hold, and power averaging", "backend/trace.py"))
story.extend(
    [
        algorithm_summary(
            "For every frequency bin: the highest observed level, the lowest valid "
            "observed level, and the average power over all processed frames.",
            "A live trace shows only one instant. Intermittent, drifting, or noisy "
            "signals are easier to understand when their history is retained.",
            "These traces reveal brief transmissions, long-term minima, and stable "
            "average spectral shapes that a single frame can miss.",
        ),
        P("Maximum hold", "Subsection"),
        P(
            "For each frequency bin, compare the new live value with the stored "
            "value and keep the larger one. A short signal remains visible after "
            "it disappears from the live trace."
        ),
        P("Minimum hold", "Subsection"),
        P(
            "For each frequency bin, keep the smaller valid value. Samples at or "
            "near the artificial -140 dBFS DSP floor are ignored because they "
            "represent numerical cancellation or underflow rather than a real "
            "receiver measurement. On initialization, invalid bins use the median "
            "of valid bins as a safe fallback."
        ),
        P("Running power average", "Subsection"),
        P(
            "The live dB value is first converted to linear power. The new running "
            "mean is updated using:"
        ),
        callout(
            "Running-mean rule",
            "new average = old average + (new power - old average) / new frame count",
        ),
        P(
            "The average is then converted back to dB for display. This update "
            "needs only the current average and frame count, so the program does "
            "not have to store every previous spectrum."
        ),
        P("Why averaging must happen in linear power", "Subsection"),
        P(
            "dB is logarithmic. Directly averaging dB values does not represent "
            "average physical power and can suppress noise-like digital modulation. "
            "The implementation therefore averages linear detector power and only "
            "uses dB for presentation."
        ),
        P("Simple example", "Subsection"),
        P(
            "If one bin is measured once at a high level and once at a low level, "
            "maximum hold keeps the high value, minimum hold keeps the low value, "
            "and average calculates the mean of their linear powers. These three "
            "results answer different questions about the same history."
        ),
    ]
)

# Power calibration
story.extend(section_header("9", "Power-calibration offset selection", "backend/power_calibration.py"))
story.extend(
    [
        algorithm_summary(
            "The correction value that must be added to a raw dBFS reading to "
            "produce an estimated physical input power in dBm.",
            "An SDR's raw digital level depends on receiver gain, frequency "
            "response, and hardware variation. Relabeling dBFS as dBm without "
            "calibration would give a believable-looking but incorrect power.",
            "The calibration logic makes absolute power readouts traceable to "
            "measured device behavior and deliberately falls back to honest dBFS "
            "when calibration is not valid.",
        ),
        P("Decision order", "Subsection"),
        BlockDiagram(
            [
                "Check calibrated<br/>VGA range",
                "Use per-VGA<br/>table if present",
                "Else use frequency<br/>table",
                "Else use constant<br/>offset",
                "Apply offset<br/>to dBFS",
            ]
        ),
        Spacer(1, 3 * mm),
        bullets(
            [
                "<b>Validity guard:</b> If the current VGA gain is below or above "
                "the characterized range, no dBm result is produced.",
                "<b>Per-VGA table:</b> This has highest priority because it directly "
                "stores the solved offset for measured gain values.",
                "<b>Frequency table:</b> If no VGA table exists, the algorithm "
                "interpolates a base offset between neighboring frequency "
                "calibration points, then subtracts the current VGA gain.",
                "<b>Constant model:</b> If the response was sufficiently uniform, "
                "one base offset is used and the VGA gain is subtracted.",
                "<b>Legacy constant:</b> An older already-solved offset is accepted "
                "for backward compatibility.",
            ]
        ),
        P("Piecewise-linear interpolation", "Subsection"),
        P(
            "When the requested gain or frequency falls between two measured "
            "calibration points, the correction is estimated along the straight "
            "line joining those points. Outside the table, the nearest endpoint is "
            "used rather than extrapolating into an unmeasured range."
        ),
        P("Simple example", "Subsection"),
        P(
            "Suppose the frequency table gives a base offset of -10 dB at 100 MHz "
            "and -20 dB at 200 MHz. At 150 MHz the interpolated base is -15 dB. "
            "With 30 dB VGA gain, the applied offset is -45 dB. A raw reading of "
            "-20 dBFS would therefore be reported as -65 dBm."
        ),
        callout(
            "Safety significance",
            "Returning no calibration outside a measured range is an important "
            "design choice. It prevents the interface from presenting fabricated "
            "absolute power merely because a numerical formula is available.",
        ),
        PageBreak(),
    ]
)

# Frequency calibration
story.extend(section_header("10", "HackRF frequency-axis correction", "backend/acquisition.py"))
story.extend(
    [
        algorithm_summary(
            "A corrected center frequency after accounting for a constant tuning "
            "error and an error that grows in proportion to frequency.",
            "A hardware oscillator can have both a fixed offset and a "
            "parts-per-million scale error. Without correction, every displayed "
            "frequency can be shifted from its true RF value.",
            "Correcting the center frequency improves the accuracy of the entire "
            "frequency axis, peak readouts, carrier edges, marker positions, and "
            "bandwidth placement.",
        ),
        P("The two-term model", "Subsection"),
        callout(
            "Frequency error",
            "error in Hz = fixed error in Hz + driver frequency x PPM error x 0.000001",
        ),
        callout(
            "Corrected frequency",
            "calibrated frequency = driver frequency - calculated error",
        ),
        P("Why two terms?", "Subsection"),
        bullets(
            [
                "The fixed term describes an error that remains approximately "
                "constant at all tuned frequencies.",
                "The PPM term describes proportional oscillator error. For the "
                "same PPM value, the error in hertz becomes larger as the tuned "
                "frequency increases.",
            ]
        ),
        P("Sign convention", "Subsection"),
        P(
            "Calibration records observed frequency minus reference frequency. A "
            "positive result means the analyzer displays too high, so the software "
            "subtracts that error from the driver frequency."
        ),
        P("Simple example", "Subsection"),
        P(
            "At a 1 GHz driver frequency, a fixed +2 kHz error and a +1 PPM error "
            "produce a total error of +3 kHz. The calibrated center becomes "
            "999.997 MHz."
        ),
        P("Backward compatibility", "Subsection"),
        P(
            "If the two-term calibration is not present, the HackRF acquisition "
            "path can still apply the older single frequency-axis offset."
        ),
        callout(
            "Scope",
            "The explicit fixed-plus-PPM correction is currently implemented in "
            "the HackRF acquisition path. USRP and Pluto use their driver-reported "
            "configured center frequencies.",
        ),
        PageBreak(),
    ]
)

# UI peak
story.extend(section_header("11", "Automatic peak tracking and marker peak search", "frontend/renderer.py and webapp/static/app.js"))
story.extend(
    [
        algorithm_summary(
            "The strongest displayed point on the user-selected trace, such as "
            "live, maximum hold, minimum hold, or average.",
            "The user often wants to see or place a marker on the most prominent "
            "visible feature immediately, without manually searching across "
            "thousands of bins.",
            "This makes the analysis interactive: the automatic red marker follows "
            "the strongest point, and peak search can place a normal marker there.",
        ),
        P("Desktop behavior", "Subsection"),
        P(
            "The desktop renderer ignores non-finite frequency or amplitude values, "
            "then performs a maximum search across the selected trace. The automatic "
            "marker is moved to that bin. Manual marker peak search uses the same "
            "basic maximum-bin idea."
        ),
        P("Web behavior", "Subsection"),
        P(
            "The browser's reusable visible-peak function scans from the first "
            "visible bin to the last visible bin and remembers the index of the "
            "largest value. It is used both for the red automatic marker and for "
            "placing a selected marker at the strongest point in the current view. "
            "The web measurement readout separately scans the full selected trace."
        ),
        P("Why this is deliberately simpler than sub-bin interpolation", "Subsection"),
        P(
            "The purpose here is graphical placement on an existing plotted data "
            "point. A marker must remain attached to an actual trace bin. The "
            "measurement engine's parabolic interpolation answers a different "
            "question: the best estimate of the real peak frequency between bins."
        ),
        callout(
            "Significance",
            "Keeping graphical peak search separate from scientific peak-frequency "
            "estimation prevents the display marker from drifting away from its "
            "actual plotted sample while still allowing a more accurate numerical "
            "measurement.",
        ),
        Spacer(1, 8 * mm),
        P("How the algorithms work together", "Section"),
        BlockDiagram(
            [
                "FFT creates<br/>frequency bins",
                "Traces preserve<br/>history",
                "Calibration fixes<br/>units and axis",
                "Detectors find<br/>signals",
                "Measurements and<br/>markers explain them",
            ]
        ),
        Spacer(1, 4 * mm),
        P(
            "No single algorithm provides the whole answer. The FFT creates the "
            "data, historical traces expose behavior over time, calibration makes "
            "the axes meaningful, carrier and peak algorithms locate interesting "
            "features, and measurement algorithms turn those features into values "
            "a person can interpret."
        ),
        PageBreak(),
    ]
)

# Summary / limitations / glossary
summary_rows = [
    [
        P("Algorithm", "TableHead"),
        P("Main result", "TableHead"),
        P("Main reason", "TableHead"),
    ],
    [
        P("Hann-windowed FFT", "TableCell"),
        P("Spectrum bins", "TableCell"),
        P("Convert IQ time samples into frequency information", "TableCell"),
    ],
    [
        P("Carrier detector", "TableCell"),
        P("Occupied regions and edges", "TableCell"),
        P("Find wide transmissions without accepting noise humps", "TableCell"),
    ],
    [
        P("Multi-peak detector", "TableCell"),
        P("Distinct local peaks", "TableCell"),
        P("Summarize several strong signals", "TableCell"),
    ],
    [
        P("Parabolic peak fit", "TableCell"),
        P("Sub-bin peak frequency", "TableCell"),
        P("Improve frequency precision without a larger FFT", "TableCell"),
    ],
    [
        P("Median noise floor", "TableCell"),
        P("Typical background bin level", "TableCell"),
        P("Resist distortion by a few strong signals", "TableCell"),
    ],
    [
        P("99% power bandwidth", "TableCell"),
        P("Occupied bandwidth", "TableCell"),
        P("Measure width from distributed signal power", "TableCell"),
    ],
    [
        P("Linear power sum", "TableCell"),
        P("Total displayed power", "TableCell"),
        P("Combine bin powers correctly", "TableCell"),
    ],
    [
        P("Hold and average traces", "TableCell"),
        P("Historical extrema and mean", "TableCell"),
        P("Reveal intermittent and long-term behavior", "TableCell"),
    ],
    [
        P("Calibration interpolation", "TableCell"),
        P("dBFS-to-dBm offset", "TableCell"),
        P("Produce honest physical power estimates", "TableCell"),
    ],
    [
        P("Fixed-plus-PPM correction", "TableCell"),
        P("Corrected HackRF frequency", "TableCell"),
        P("Compensate oscillator tuning error", "TableCell"),
    ],
    [
        P("UI maximum search", "TableCell"),
        P("Strongest plotted point", "TableCell"),
        P("Make markers fast and intuitive", "TableCell"),
    ],
]

summary_table = Table(
    summary_rows,
    colWidths=[44 * mm, 45 * mm, CONTENT_WIDTH - 89 * mm],
    repeatRows=1,
)
summary_table.setStyle(
    TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), BLUE),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, PALE_GREY]),
            ("GRID", (0, 0), (-1, -1), 0.4, LINE),
            ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
            ("TOPPADDING", (0, 0), (-1, -1), 1.5 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 * mm),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]
    )
)

story.extend(
    [
        P("One-page summary", "Section"),
        summary_table,
        Spacer(1, 5 * mm),
        P("Important limitations to remember", "Subsection"),
        bullets(
            [
                "Frequency resolution is limited by sample rate, FFT size, window, "
                "and signal-to-noise ratio.",
                "The measurement noise floor is the median of the whole display; it "
                "is not a locally measured noise floor beside one carrier.",
                "Occupied bandwidth and channel power currently include the entire "
                "displayed span, including noise and unrelated signals.",
                "Carrier detection requires a sustained core and rejects incomplete "
                "regions at FFT edges. Very narrow tones are therefore better "
                "represented by peak detection than carrier-region detection.",
                "A dBm label is only trustworthy when the live frequency and gain "
                "fall within valid calibration coverage.",
            ]
        ),
        P("Short glossary", "Subsection"),
        P(
            "<b>Carrier:</b> A continuous occupied frequency region used to carry "
            "information. <b>FFT:</b> A fast method for separating a sampled "
            "waveform into frequency components. <b>Bin:</b> One discrete "
            "frequency slot in the FFT. <b>Noise floor:</b> The background level "
            "against which signals are seen. <b>Hysteresis:</b> Using a stricter "
            "condition to start a detection and a looser condition to continue it. "
            "<b>MAD:</b> Median absolute deviation, a robust measure of variation. "
            "<b>dBFS:</b> Digital level relative to full scale. <b>dBm:</b> Power "
            "relative to one milliwatt. <b>PPM:</b> Parts per million, used for "
            "small proportional frequency errors."
        ),
        Spacer(1, 3 * mm),
        P(
            "End of guide. Source reviewed from the current project implementation.",
            "Small",
        ),
    ]
)


def build() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        rightMargin=MARGIN_X,
        leftMargin=MARGIN_X,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title="Frequency Analyzer Algorithms Explained",
        author="Frequency Analyzer Project",
        subject="Plain-language explanation of report-worthy algorithms",
    )
    document.build(story, onFirstPage=page_decor, onLaterPages=page_decor)
    print(OUTPUT)


if __name__ == "__main__":
    build()
