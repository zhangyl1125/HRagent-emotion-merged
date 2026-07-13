import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useWorkflow } from '../../context/WorkflowContext';
import type { EmployeeRecord } from '../../types/domain';
import { profileRows } from '../../utils/format';

function employeeInputLabel(record: EmployeeRecord | null) {
  if (!record) return '';
  const name = record.name || record.employee_alias || '员工';
  return maskEmployeeName(String(name));
}

function maskEmployeeName(name: string) {
  const value = name.trim();
  if (!value) return '员工*';
  const firstToken = value.split(/[\s\/]+/).find(Boolean) || value;
  return `${Array.from(firstToken)[0] || '员'}*`;
}

export default function ProfileStep() {
  const navigate = useNavigate();
  const {
    profileText,
    setProfileText,
    selectedFile,
    setSelectedFile,
    employeeResults,
    selectedEmployee,
    displayedProfile,
    lookupEmployee,
    selectEmployee,
    confirmProfile,
  } = useWorkflow();
  const [employeeQuery, setEmployeeQuery] = useState('');
  const [resultsOpen, setResultsOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const previewRows = displayedProfile ? profileRows(displayedProfile).filter(([, label]) => label !== '员工代称') : [];

  useEffect(() => {
    if (!selectedEmployee) return;
    setEmployeeQuery(employeeInputLabel(selectedEmployee));
    setResultsOpen(false);
  }, [selectedEmployee]);

  useEffect(() => {
    const textarea = composerRef.current;
    if (!textarea) return;
    textarea.style.height = 'auto';
    textarea.style.height = `${textarea.scrollHeight}px`;
  }, [profileText]);

  const handleEmployeeLookup = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    await lookupEmployee(employeeQuery);
    setResultsOpen(true);
  };

  const handleSelectEmployee = (record: EmployeeRecord) => {
    setEmployeeQuery(employeeInputLabel(record));
    setResultsOpen(false);
    selectEmployee(record);
  };

  const submit = async () => {
    await confirmProfile();
    navigate('/app/intent');
  };

  const showResults = resultsOpen && employeeResults.length > 0;

  return (
    <section id="screen-profile" className="screen active">
      <div className="page-intro">
        <h1>员工信息</h1>
      </div>
      <div className="split-layout profile-layout">
        <div className="stack input-workspace">
          <section className="soft-card employee-lookup-card section-card-accent">
            <div className="card-title"><span className="title-icon">ID</span><div><h2>员工库匹配</h2></div></div>
            <form className="lookup-grid" onSubmit={handleEmployeeLookup}>
              <label className="lookup-field"><span>员工姓名或工号</span><input value={employeeQuery} onChange={(event) => { setEmployeeQuery(event.target.value); setResultsOpen(false); }} onFocus={() => employeeResults.length > 0 && setResultsOpen(true)} type="search" aria-label="员工姓名或工号" placeholder="员工姓名 / 工号 / 代称，例如：张三 / Alex / E001" autoComplete="off" /></label>
              <button className="btn btn-primary" type="submit">匹配员工</button>
            </form>
            {showResults && (
              <div className="employee-results" role="listbox" aria-label="员工匹配结果">
                {employeeResults.map((record) => {
                  const alias = record.employee_alias || record.name || '员工';
                  const selected = selectedEmployee?.employee_id === record.employee_id;
                  return (
                    <button key={String(record.employee_id || record.name)} className={`employee-result ${selected ? 'selected' : ''}`} type="button" onClick={() => handleSelectEmployee(record)}>
                      <span className="employee-avatar-mini">{String(alias).slice(0, 1).toUpperCase()}</span>
                      <span className="employee-result-main"><strong>{maskEmployeeName(String(record.name || alias))}</strong></span>
                      <span className="employee-result-pick">{selected ? '已选择' : '选择'}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </section>

          <section className="soft-card profile-composer-card">
            <div className="card-title"><span className="title-icon">BG</span><div><h2>补充员工信息</h2></div></div>
            <div
              className={`profile-composer ${dragging ? 'dragover' : ''}`}
              onDragEnter={(event) => { event.preventDefault(); setDragging(true); }}
              onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
              onDragLeave={(event) => { event.preventDefault(); setDragging(false); }}
              onDrop={(event) => {
                event.preventDefault();
                setDragging(false);
                setSelectedFile(event.dataTransfer.files[0] || null);
              }}
            >
              <label className="composer-upload-button" htmlFor="docFile" aria-label="上传参考资料" title="上传参考资料">
                <input id="docFile" type="file" onChange={(event) => setSelectedFile(event.target.files?.[0] || null)} />
                <span aria-hidden="true">+</span>
              </label>
              <div className="composer-input-area">
                {selectedFile && <div className="attachment-chip" title={selectedFile.name}>{selectedFile.name}</div>}
                <textarea
                  id="profileText"
                  ref={composerRef}
                  className="profile-composer-textarea"
                  value={profileText}
                  onChange={(event) => setProfileText(event.target.value)}
                  rows={1}
                  placeholder="补充员工相关信息，例如个人诉求、历史反馈、生活情况、敏感约束。"
                />
              </div>
            </div>
          </section>

          <div className="bottom-action profile-action"><button className="btn btn-primary btn-wide" type="button" onClick={submit}>确认员工信息</button></div>
        </div>

        <section className="soft-card profile-card summary-panel">
          <div className="card-title"><span className="title-icon">HR</span><div><h2>员工档案预览</h2></div></div>
          <div className="profile-preview">
            {!previewRows.length && <div className="empty-state">请先在左侧匹配并选择员工，或补充员工背景。</div>}
            {previewRows.map(([, label, value]) => (
              <div className="profile-row" key={label}>
                <span>{label}</span>
                <strong>{label === '当前绩效评级' ? <span className="rating-pill">{value}</span> : value}</strong>
              </div>
            ))}
          </div>
        </section>
      </div>
    </section>
  );
}
