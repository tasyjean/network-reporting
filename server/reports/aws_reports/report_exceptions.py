class ReportException(Exception):
    def __init__(self, message = None, jobflowid = None):
        self.report_message = message 
        self.jobflowid = jobflowid

class MRSubmitError(ReportException):
    def __init__(self, reason, message):
        self.reason = reason
        self.report_message = message

class NoDataError(MRSubmitError):
    pass

class ReportParseError(ReportException):
    pass

class BlobUploadError(ReportException):
    pass

class S3Error(ReportException):
    pass

class ReportPutError(ReportException):
    pass

class ReportNotifyError(ReportException):
    pass
