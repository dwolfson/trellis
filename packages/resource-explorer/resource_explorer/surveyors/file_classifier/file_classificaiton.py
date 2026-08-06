
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class FileClassification:
    fileName: str
    pathName: str
    fileExtension: Optional[str]
    creationTime: Optional[datetime]
    lastModifiedTime: Optional[datetime]
    lastAccessedTime: Optional[datetime]
    canRead: bool
    canWrite: bool
    canExecute: bool
    isHidden: bool
    isSymLink: bool
    fileType: Optional[str] = None
    deployedImplementationType: Optional[str] = None
    encoding: Optional[str] = None
    assetTypeName: Optional[str] = None
    fileSize: int = 0