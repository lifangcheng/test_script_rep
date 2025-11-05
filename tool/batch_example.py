"""Example usage of batch processing functionality"""

import logging
from test_batch import (BatchProcessor, process_file_input,
                       process_url_input, process_api_input)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    """Example batch processing workflow"""
    
    # Initialize processor
    headers = ["测试名称", "需求编号", "需求描述", "测试描述", 
              "前置条件", "测试步骤", "预期结果", "需求追溯"]
    processor = BatchProcessor(
        model="MiMo-7B-RL",
        base_url="http://model.mify.ai.srv",
        headers=headers,
        dynamic_mode=True,
        dynamic_params={
            "min_total": 3,
            "max_total": 9,
            "pos_w": 3.0,
            "neg_w": 2.0,
            "edge_w": 2.0
        }
    )
    
    # Collect requirements from different sources
    requirements = []
    
    # 1. From Excel
    excel_reqs = process_file_input('requirements.xlsx')
    requirements.extend(excel_reqs)
    logger.info(f"Added {len(excel_reqs)} requirements from Excel")
    
    # 2. From Word doc
    word_reqs = process_file_input('spec.docx')
    requirements.extend(word_reqs)
    logger.info(f"Added {len(word_reqs)} requirements from Word")
    
    # 3. From URLs
    urls = [
        "https://example.com/req1",
        "https://example.com/req2"
    ]
    for url in urls:
        url_reqs = process_url_input(url)
        requirements.extend(url_reqs)
        logger.info(f"Added {len(url_reqs)} requirements from {url}")
        
    # 4. From API
    api_reqs = process_api_input(
        "https://api.example.com/requirements",
        headers={"Authorization": "Bearer token"}
    )
    requirements.extend(api_reqs)
    logger.info(f"Added {len(api_reqs)} requirements from API")
    
    # Process all requirements
    logger.info(f"Processing {len(requirements)} total requirements")
    
    try:
        df = processor.process_batch(requirements)
        
        # Save results
        df.to_excel("test_cases_batch.xlsx", index=False)
        df.to_csv("test_cases_batch.csv", index=False)
        
        logger.info(f"Generated {len(df)} test cases")
        
        # Check for errors
        errors = processor.get_errors()
        if errors:
            logger.warning(f"Encountered {len(errors)} errors:")
            for req_id, error in errors:
                logger.warning(f"  {req_id}: {error}")
                
    except Exception as e:
        logger.error(f"Batch processing failed: {e}")

if __name__ == "__main__":
    main()