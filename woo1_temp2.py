import OpenDartReader
import pandas as pd
from datetime import datetime

def get_latest_debt_ratio(dart, corp_code, base_date):
  """
  특정 일자 기준 가장 최근 부채비율을 조회합니다.

  Parameters:
  dart: OpenDartReader 객체
  corp_code: 공시대상회사의 고유번호(8자리)
  base_date: 기준일자 (예: '20240120')

  Returns:
  dict: 부채비율 데이터
  """
  try:
    # 기준일자로부터 가장 최근 공시 재무제표 조회
    year = int(base_date[:4])
    month = int(base_date[4:6])

    # 분기 결정
    if month >= 1 and month <= 3:
      year = year - 1
      reprt_code = '11011'  # 사업보고서
    elif month >= 4 and month <= 5:
      reprt_code = '11013'  # 1분기보고서
    elif month >= 6 and month <= 8:
      reprt_code = '11012'  # 반기보고서
    elif month >= 9 and month <= 11:
      reprt_code = '11014'  # 3분기보고서
    else:
      reprt_code = '11011'  # 사업보고서

    # 재무제표 조회
    fs = dart.finstate(corp_code, year, reprt_code=reprt_code)

    if fs is None or fs.empty:
      return None

    # 필요한 계정과목 찾기
    total_debt = fs[fs['account_nm'].str.contains('부채총계', na=False)]['thstrm_amount'].iloc[0]
    total_equity = fs[fs['account_nm'].str.contains('자본총계', na=False)]['thstrm_amount'].iloc[0]

    # 문자열을 숫자로 변환
    total_debt = int(total_debt.replace(',', ''))
    total_equity = int(total_equity.replace(',', ''))

    # 부채비율 계산 (부채총계/자본총계 * 100)
    debt_ratio = (total_debt / total_equity) * 100

    # 보고서 구분
    report_type = {
      '11011': '사업보고서',
      '11012': '반기보고서',
      '11013': '1분기보고서',
      '11014': '3분기보고서'
    }

    return {
      'year': year,
      'report_type': report_type[reprt_code],
      'total_debt': total_debt,
      'total_equity': total_equity,
      'debt_ratio': round(debt_ratio, 2)
    }

  except Exception as e:
    print(f"Error processing {corp_code}: {e}")
    return None

def analyze_companies_debt_ratio(api_key, companies, base_date):
  """
  여러 기업의 최근 부채비율을 분석합니다.

  Parameters:
  api_key: DART API 키
  companies: [(corp_code, company_name)] 형태의 리스트
  base_date: 기준일자 (예: '20240120')
  """
  # DART API 초기화
  dart = OpenDartReader(api_key)

  results = []

  for corp_code, company_name in companies:
    ratio_data = get_latest_debt_ratio(dart, corp_code, base_date)
    if ratio_data:
      ratio_data['company_name'] = company_name
      results.append(ratio_data)

  # 결과를 DataFrame으로 변환
  if results:
    df = pd.DataFrame(results)
    df = df[['company_name', 'year', 'report_type', 'total_debt', 'total_equity', 'debt_ratio']]
    return df

  return None

# 사용 예시
if __name__ == "__main__":
  API_KEY = 'YOUR_API_KEY'  # DART API 키 입력

  # 분석할 기업 리스트 [(고유번호, 기업명)]
  companies = [
    ('00126380', '삼성전자'),
    ('00164779', '현대자동차'),
    # 추가 기업들...
  ]

  # 기준일자 설정
  base_date = '20240120'

  # 분석 실행
  results_df = analyze_companies_debt_ratio(API_KEY, companies, base_date)

  if results_df is not None:
    # 결과 출력
    pd.set_option('display.float_format', lambda x: '%.2f' % x)
    print(f"\n=== 기업별 부채비율 분석 결과 (기준일: {base_date}) ===")
    print(results_df)

    # CSV 파일로 저장
    results_df.to_csv('latest_debt_ratio.csv', index=False, encoding='utf-8-sig')
    print("\n분석 결과가 'latest_debt_ratio.csv' 파일로 저장되었습니다.")