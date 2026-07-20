from __future__ import annotations
import feedback_cli
from face_memory import train_from_jsonl

class AutoTrainingReviewStore(feedback_cli.ReviewStore):
    def label(self,key:str,label:str):
        super().label(key,label)
        try:
            train_from_jsonl(self.feedback_path,self.feedback_path.with_name("face_memory.json"))
        except RuntimeError:
            # The calibrator intentionally stays inactive until both classes have
            # at least two labels. YuNet + geometric safety rules remain active.
            pass

feedback_cli.ReviewStore=AutoTrainingReviewStore
if __name__=="__main__":feedback_cli.main()
