import pathlib
import os
import shutil
from datetime import datetime
from typing import Optional
from resource_explorer.surveyors.file_classifier.file_classificaiton import FileClassification

class FileReferenceDataCache:
    def __init__(self, file_type: Optional[str] = None, 
                 asset_type_name: Optional[str] = None, 
                 encoding: Optional[str] = None, 
                 deployed_implementation_type: Optional[str] = None):
        self.fileType: Optional[str] = file_type
        self.assetTypeName: Optional[str] = asset_type_name
        self.encoding: Optional[str] = encoding
        self.deployedImplementationType: Optional[str] = deployed_implementation_type

class FileClassifier:
    def __init__(self, pyegeria_client):
        self.pyegeria_client = pyegeria_client
        self.fileNameReferenceDataCache = {}
        self.fileExtensionReferenceDataCache = {}

    def get_file_extension(self, file_name: str) -> Optional[str]:
        if not file_name:
            return None
        if file_name.startswith('.') and file_name.count('.') == 1:
            return None
        parts = file_name.split('.')
        if len(parts) > 1:
            return parts[-1]
        return None

    def classify_file(self, path_name: str) -> FileClassification:
        return self.classify_file_object(pathlib.Path(path_name))

    def classify_file_object(self, path: pathlib.Path) -> FileClassification:
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        stat = path.stat()
        
        file_name = path.name
        path_name = str(path.absolute())
        file_extension = self.get_file_extension(file_name)
        
        creation_time = datetime.fromtimestamp(stat.st_ctime)
        last_modified_time = datetime.fromtimestamp(stat.st_mtime)
        last_accessed_time = datetime.fromtimestamp(stat.st_atime)
        
        can_read = os.access(path, os.R_OK)
        can_write = os.access(path, os.W_OK)
        can_execute = os.access(path, os.X_OK)
        
        is_hidden = file_name.startswith('.')
        is_sym_link = path.is_symlink()
        file_size = stat.st_size

        # Metadata Lookup
        ref_data = self.lookup_file_reference_data(file_name, file_extension)

        return FileClassification(
            fileName=file_name,
            pathName=path_name,
            fileExtension=file_extension,
            creationTime=creation_time,
            lastModifiedTime=last_modified_time,
            lastAccessedTime=last_accessed_time,
            canRead=can_read,
            canWrite=can_write,
            canExecute=can_execute,
            isHidden=is_hidden,
            isSymLink=is_sym_link,
            fileType=ref_data.fileType if ref_data else None,
            deployedImplementationType=ref_data.deployedImplementationType if ref_data else None,
            encoding=ref_data.encoding if ref_data else None,
            assetTypeName=ref_data.assetTypeName if ref_data else None,
            fileSize=file_size
        )

    def lookup_file_reference_data(self, file_name: str, file_extension: Optional[str]) -> FileReferenceDataCache:
        # Check cache first
        if file_name in self.fileNameReferenceDataCache:
            return self.fileNameReferenceDataCache[file_name]
        
        if file_extension and file_extension in self.fileExtensionReferenceDataCache:
            return self.fileExtensionReferenceDataCache[file_extension]

        # Call pyegeria to fetch metadata
        ref_data = FileReferenceDataCache()
        
        if self.pyegeria_client:
            try:
                # Try by filename first
                found_data = self.pyegeria_client.get_valid_metadata_value(
                    property_name="fileName",
                    type_name="DataFile",
                    preferred_value=file_name
                )
                
                if found_data and isinstance(found_data, dict):
                    ref_data = self._map_valid_value_to_cache(found_data)
                elif file_extension:
                    # Try by extension if filename didn't yield specific data
                    found_data = self.pyegeria_client.get_valid_metadata_value(
                        property_name="fileExtension",
                        type_name="DataFile",
                        preferred_value=file_extension
                    )
                    if found_data and isinstance(found_data, dict):
                        ref_data = self._map_valid_value_to_cache(found_data)

            except Exception:
                # Basic error handling, return default empty ref_data
                pass

        # Update caches (even if empty/default to avoid repeated failed lookups)
        self.fileNameReferenceDataCache[file_name] = ref_data
        if file_extension:
            self.fileExtensionReferenceDataCache[file_extension] = ref_data
            
        return ref_data

    def _map_valid_value_to_cache(self, valid_value: dict) -> FileReferenceDataCache:
        """
        Maps a ValidMetadataValue object (as a dict) from Egeria to FileReferenceDataCache.
        In Egeria, additional properties of the ValidMetadataValue contain the mapping.
        """
        props = valid_value.get("properties", {})
        add_props = props.get("additionalProperties", {})
        
        return FileReferenceDataCache(
            file_type=add_props.get("fileType"),
            asset_type_name=add_props.get("assetTypeName"),
            encoding=add_props.get("encoding"),
            deployed_implementation_type=add_props.get("deployedImplementationType")
        )