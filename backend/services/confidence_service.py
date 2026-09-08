def summarise_confidence(objects):
    def mean(kind):
        values = [
            x["confidence"]
            for x in objects
            if x["source"] == "yolo" and (x["kind"] == "existing_pv") == kind
        ]
        return round(sum(values) / len(values), 3) if values else None

    values = [x["confidence"] for x in objects if x["source"] == "yolo"]
    return {
        "existing_pv": mean(True),
        "obstacles": mean(False),
        "mean_detection": round(sum(values) / len(values), 3) if values else None,
        "uncertain_objects": sum(v < 0.5 for v in values),
        "note": "Model detection scores are not calibrated probabilities of layout correctness.",
    }
