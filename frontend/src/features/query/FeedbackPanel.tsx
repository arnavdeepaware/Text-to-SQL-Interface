import { SyntheticEvent, useRef, useState } from "react";

import { apiClient } from "../../api/client";
import type { FeedbackRating } from "../../types/api";

interface FeedbackPanelProps {
  requestId: string;
}

type FeedbackStatus = "idle" | "submitting" | "success" | "failed";

export function FeedbackPanel({ requestId }: FeedbackPanelProps) {
  const [rating, setRating] = useState<FeedbackRating | null>(null);
  const [comment, setComment] = useState("");
  const [status, setStatus] = useState<FeedbackStatus>("idle");
  const [message, setMessage] = useState<string | null>(null);
  const submissionLockedRef = useRef(false);

  const isLocked = status === "submitting" || status === "success";
  const canSubmit = rating !== null && !isLocked;

  function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (rating === null || isLocked) {
      return;
    }

    void submitFeedback(rating);
  }

  async function submitFeedback(selectedRating: FeedbackRating) {
    if (submissionLockedRef.current) {
      return;
    }

    submissionLockedRef.current = true;
    setStatus("submitting");
    setMessage(null);

    try {
      await apiClient.submitFeedback({
        request_id: requestId,
        rating: selectedRating,
        comment: comment.trim().length > 0 ? comment.trim() : null
      });
      setStatus("success");
      setMessage("Feedback recorded.");
    } catch (error) {
      submissionLockedRef.current = false;
      setStatus("failed");
      setMessage(error instanceof Error ? error.message : "Feedback could not be recorded.");
    }
  }

  return (
    <section className="feedback-panel" aria-labelledby="feedback-heading">
      <h3 id="feedback-heading">Result feedback</h3>
      <form onSubmit={handleSubmit}>
        <fieldset disabled={isLocked}>
          <legend>Mark this result</legend>
          <div className="rating-options">
            {(["correct", "incorrect", "unsure"] as const).map((option) => (
              <label key={option}>
                <input
                  type="radio"
                  name={`feedback-${requestId}`}
                  value={option}
                  checked={rating === option}
                  onChange={() => {
                    setRating(option);
                  }}
                />
                {option}
              </label>
            ))}
          </div>
        </fieldset>
        <label htmlFor={`feedback-comment-${requestId}`}>Optional comment</label>
        <textarea
          id={`feedback-comment-${requestId}`}
          value={comment}
          onChange={(event) => {
            setComment(event.target.value);
          }}
          disabled={isLocked}
          maxLength={500}
          rows={3}
        />
        <div className="feedback-actions">
          <button type="submit" disabled={!canSubmit}>
            {status === "submitting" ? "Sending" : "Send feedback"}
          </button>
          {message !== null ? (
            <p
              className={
                status === "failed"
                  ? "feedback-message feedback-message--error"
                  : "feedback-message"
              }
              role={status === "failed" ? "alert" : "status"}
            >
              {message}
            </p>
          ) : null}
        </div>
      </form>
    </section>
  );
}
