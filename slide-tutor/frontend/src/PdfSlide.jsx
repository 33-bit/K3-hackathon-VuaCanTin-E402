import { useEffect, useRef, useState } from "react";
import { Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/TextLayer.css";

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

function PdfSlide({ pageNumber, compact = false }) {
  const frameRef = useRef(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return undefined;

    const updateWidth = () => {
      const nextWidth = frame.getBoundingClientRect().width;
      setWidth((current) => Math.abs(current - nextWidth) > 0.5 ? nextWidth : current);
    };
    updateWidth();
    const observer = new ResizeObserver(updateWidth);
    observer.observe(frame);
    return () => observer.disconnect();
  }, []);

  return (
    <div className={`pdf-slide-frame ${compact ? "is-compact" : ""}`} ref={frameRef}>
      {width > 0 && (
        <Page
          pageNumber={pageNumber}
          width={width}
          renderAnnotationLayer={false}
          renderTextLayer={!compact}
          loading={<span className="pdf-page-loading" aria-label={`Loading slide ${pageNumber}`} />}
        />
      )}
    </div>
  );
}

export default PdfSlide;
