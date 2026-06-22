<?php
if (!defined("_GNUBOARD_")) exit; // 개별 페이지 접근 불가
include_once(G5_EDITOR_LIB);

auth_check($auth[$sub_menu], "w");

set_session('ss_view_'.$bo_table.'_'.$wr_id, true);

$token = get_token();

$g5['title'] = "답변 하기 " . $html_title;
include_once(G5_ADMIN_PATH."/admin.head.php");

$is_dhtml_editor = false;

$ss_wr_qna = (isset($_SESSION['ss_wr_qna']) && $_SESSION['ss_wr_qna'] ? $_SESSION['ss_wr_qna'] : '');
unset($_SESSION['ss_wr_qna']);
$wr2 = explode('|', $view['wr_2']); // wr_2_1 ~ 2
$wr3 = explode('|', $view['wr_3']); // wr_3_1 ~ 5
$wr4 = explode('|', $view['wr_4']); // wr_4_1 ~ 2
$wr8 = explode('|', $view['wr_8']); // wr_8_1 ~ 39

//상담신청 회원정보
$mb = get_member($view['mb_id']);
$mb_nick = get_sideview($mb['mb_id'], $mb['mb_name'], $mb['mb_email'], $mb['mb_homepage']);

?>
<style>
table caption {font-size: 1.2em;line-height: normal;height: auto;text-align: left;margin-bottom: 10px;margin-top: 20px;font-weight: bold;}
#pre_qna_list {}
#pre_qna_list ul {width:99%;margin:0;padding:0;list-style:none}
#pre_qna_list ul li.title {padding:8px 0;background:#e5e5e5;border-bottom:1px solid #bbb}
#pre_qna_list ul li.conts {display:none}
#pre_qna_list ul li .subject {margin-left:10px;font-weight:bold;color:blue}
#pre_qna_list ul li .subject2 {margin-left:10px;color:#cd7444}
#pre_qna_list ul li .time {margin-left:10px;font-weight:normal;color:#333}

#pre_buy_list {}
#pre_buy_list ul {width:99%;margin:0;padding:0;list-style:none}
#pre_buy_list ul li {padding:8px 0;background:#e5e5e5;border-bottom:1px solid #bbb}
#pre_buy_list ul li .subject {margin-left:10px;font-weight:bold;color:blue}
#pre_buy_list ul li .time {margin-left:10px}

#wr_content {height:300px}

.grid_3 {width: 15%;}
.grid {width: 35%;}

.tbl_frm01 textarea {font-size: 15px;padding: 10px;}
</style>
<div class="tbl_frm01 tbl_wrap">
	<table>
	<caption>※ 작성자 정보</caption>
	<colgroup>
        <col class="grid_3">
        <col class="grid">
        <col class="grid_3">
        <col class="grid">
    </colgroup>
	<tbody>
	<tr>
        <th scope="row">아이디</th>
        <td><?php echo $mb['mb_id']?></td>
        <th scope="row">이름</th>
        <td><?php echo $mb_nick?></td>
    </tr>
	<tr>
        <th scope="row">연락처</th>
        <td><?php echo $mb['mb_tel']?></td>
        <th scope="row">핸드폰</th>
		<td><?php echo $mb['mb_hp']?></td>
    </tr>
	<tr>
        <th scope="row">이메일</th>
		<td><?php echo $mb['mb_email']?></td>
        <th scope="row">홈페이지</th>
        <td><?php echo $mb['mb_homepage']?></td>
    </tr>
	<tr>
        <th scope="row">주소</th>
        <td>
           <?php echo "({$mb['mb_zip1']}-{$mb['mb_zip2']}) {$mb['mb_addr1']} {$mb['mb_addr2']}"?>
        </td>
        <th scope="row">별명</th>
		<td><?php echo $mb['mb_nick']?></td>
    </tr>
	<tr>
        <th scope="row">생년월일</th>
        <td><?php echo $mb['mb_birth']?></td>
        <th scope="row">성별</th>
		<td><?php echo $mustMent[$mb['mb_sex']]?></td>
    </tr>
	</tbody>
	</table>
</div>

<div class="tbl_frm01 tbl_wrap">
	<table>
	<caption>※ 건강정보 (필수)</caption>
	<colgroup>
        <col class="grid_3">
        <col class="grid">
        <col class="grid_3">
        <col class="grid">
    </colgroup>
	<tbody>
	<tr>
        <th scope="row">제목</th>
        <td><?php echo $write['wr_subject']?></td>
        <th scope="row">이름</th>
        <td><?php echo $mb['mb_name']?></td>
    </tr>
	<tr>
        <th scope="row">대상성별</th>
        <td><?php echo $mustMent[$view['wr_1']]?></td>
		<th scope="row">대상나이</th>
        <td><?php echo $mustMent[$wr2[0]]?>&nbsp;<?php echo ($wr2[1]) ? '('.$wr2[1].')' : ''?></td>
    </tr>
	<tr>
        <th scope="row">관심분야</th>
        <td colspan="3">
			<?php
			$comma = '';
			foreach($wr3 as $val) {
				if($val) {
					echo $comma.$mustMent[$val];
					$comma = ', ';
				}
			}
			?>
		</td>
    </tr>
	<tr>
        <th scope="row">임산부/수유부</th>
        <td colspan="3"><?php echo $mustMent[$wr4[0]]?>&nbsp;<?php echo ($wr4[1]) ? '('.$wr4[1].')' : ''?></td>
    </tr>
	</tbody>
	</table>
</div>

<?php if($view['ca_name'] == '상담') { ?>
<div class="tbl_frm01 tbl_wrap">
	<table>
	<caption>※ 기본질문</caption>
	<colgroup>
        <col class="grid_3">
        <col class="grid">
        <col class="grid_3">
        <col class="grid">
    </colgroup>
	<tbody>
	<tr>
        <th scope="row">체중</th>
        <td colspan="3"><?php echo $mustMent[$view['wr_5']]?></td>
    </tr>
	<tr>
        <th scope="row">현재 섭취중인 건강기능식품 및 기타제품</th>
        <td colspan="3"><?php echo $view['wr_6']?></td>
    </tr>
	<tr>
        <th scope="row">관심 있는 제품</th>
        <td colspan="3"><?php echo $view['wr_7']?></td>
    </tr>
	</tbody>
	</table>
</div>

<div class="tbl_frm01 tbl_wrap">
	<table>
	<caption>※ 체크리스트</caption>
	<colgroup>
        <col class="grid_3">
        <col class="grid">
        <col class="grid_3">
        <col class="grid">
    </colgroup>
	<tbody>
	<tr>
        <th scope="row">야식 섭취량</th>
        <td><?php echo $mustMent[$wr8['0']]?></td>
		<th scope="row">밀가루 음식(간식, 식사) 섭취량</th>
        <td><?php echo $mustMent[$wr8['1']]?></td>
    </tr>
	<tr>
        <th scope="row">우유, 유제품 섭취량</th>
        <td><?php echo $mustMent[$wr8['2']]?></td>
		<th scope="row">커피, 청량음료 섭취량</th>
        <td><?php echo $mustMent[$wr8['3']]?></td>
    </tr>
	<tr>
        <th scope="row">수분(200ml컵 기준) 섭취량</th>
        <td><?php echo $mustMent[$wr8['4']]?></td>
		<th scope="row">음주 정도</th>
        <td><?php echo $mustMent[$wr8['5']]?></td>
    </tr>
	<tr>
        <th scope="row">수면</th>
        <td>수면시간 (<?php echo $mustMent[$wr8['6']]?>)&nbsp;&nbsp;&nbsp;수면의질 (<?php echo $mustMent[$wr8['7']]?>)</td>
		<th scope="row">정신적 스트레스, 육체적 노동</th>
        <td><?php echo $mustMent[$wr8['8']]?></td>
    </tr>
	<tr>
        <th scope="row">운동여부(하루30분이상)</th>
        <td><?php echo $mustMent[$wr8['9']]?></td>
		<th scope="row">흡연여부</th>
        <td><?php echo $mustMent[$wr8['10']]?></td>
    </tr>
	<tr>
        <th scope="row">어른/아이 공통체크</th>
        <td colspan="3">
			<?php
			$comma = '';
			for($i=11; $i<=27; $i++) {
				if($wr8[$i]) {
					echo $comma.$mustMent[$wr8[$i]];
					$comma = ', ';
				}
			}
			?>
		</td>
    </tr>
	<tr>
        <th scope="row">여성 추가체크</th>
        <td colspan="3">
			<?php
			$comma = '';
			for($i=28; $i<=32; $i++) {
				if($wr8[$i]) {
					echo $comma.$mustMent[$wr8[$i]];
					$comma = ', ';
				}
			}
			?>
		</td>
    </tr>
	<tr>
        <th scope="row">아이 추가체크</th>
        <td colspan="3">
			<?php
			$comma = '';
			for($i=33; $i<=37; $i++) {
				if($wr8[$i]) {
					echo $comma.$mustMent[$wr8[$i]];
					$comma = ', ';
				}
			}
			?>
		</td>
    </tr>
	</tbody>
	</table>
</div>
<?php } ?>

<form name="form_rev" id="form_rev" method="post" action="qna2_form_update_new.php" autocomplete="off" > <!-- onsubmit="return form_rev_submit(this);" -->
<input type="hidden" name="w" id="w" value="u">
<input type="hidden" name="page" value="<?php echo $page?>">
<input type="hidden" name="token" value="<?php echo $token?>">
<input type="hidden" name="wr_id" value="<?php echo $wr_id?>">
<input type="hidden" name="is_dhtml_editor" value="<?php echo ($is_dhtml_editor ? '1' : '0'); ?>">
<div class="tbl_frm01 tbl_wrap">
	<table>
	<caption>※ <?php echo $view['ca_name']?>정보</caption>
	<colgroup>
        <col class="grid_3">
        <col class="grid">
        <col class="grid_3">
        <col class="grid">
    </colgroup>
	<tbody>
	<tr>
		<th colspan="2" scope="row" style="width: 50%;">이전 상담/문의 목록</th>
		<th colspan="2" scope="row" style="width: 50%;">구매목록</th>
	</tr>
	<tr>
        <td colspan="2" valign="top">
			<div id="pre_qna_list"></div>
		</td>
        <td colspan="2" valign="top">
			<div id="pre_buy_list"></div>
		</td>
    </tr>
	<tr>
        <th scope="row"><?php echo $view['ca_name']?> 내용</th>
        <td colspan="3">
			<textarea name="wr_content" id="wr_content"><?php echo $view['wr_content']?></textarea>
		</td>
    </tr>
	<tr>

    </tr>
	<tr>
        <th scope="row">관리자답변</th>
        <td colspan="3">
 	        <?php // echo cheditor2('wr_qna', ($ss_wr_qna ? $ss_wr_qna : $view['wr_qna']));?>
	        <?php echo editor_html('wr_qna', $view['wr_qna'], $is_dhtml_editor, 'form_rev'); ?>
	    </td>
    </tr>
    <tr>
        <th scope="row">회원메모(공통)</th>
        <td colspan="3"><textarea name="mb_admin_memo" id="mb_admin_memo" style="height: 400px;"><?php echo $mb['mb_admin_memo'] ?></textarea></td>
    </tr>
	<?php if($view['ca_name'] == '상담') { ?>
	<tr>
        <th scope="row">
			문의하기답변<br>
			<input type="checkbox" name="wr_qna_copy" id="wr_qna_copy" value="1"> <label for="wr_qna_copy">복사</label>
		</th>
        <td colspan="3">
	        <?php // echo cheditor2('wr_qna2', '');?>
			<?php echo editor_html('wr_qna2', $view['wr_qna2'], $is_dhtml_editor, 'form_rev'); ?>
	    </td>
    </tr>
	<?php } ?>

	<tr>
		<th scope="row">첨부파일</th>
		<td>
			<?php
			// 가변 파일
	        for ($i=0; $i<count($view['file']); $i++) {
	            if (isset($view['file'][$i]['source']) && $view['file'][$i]['source']) {
	         ?>
			<a href="<?php echo $view['file'][$i]['href'];  ?>" class="view_file_download">
                <strong><?php echo $view['file'][$i]['source'] ?></strong>
            </a>
			<?php
           		}
	        }
	         ?>
		</td>
	</tr>
	<tr>
        <th scope="row">SMS발송</th>
        <td colspan="3">
			<input type="checkbox" name="sms" id="sms" checked value="발송"> <label for="sms">예</label>
		</td>
    </tr>
	</tbody>
	</table>
</div>

<div class="btn_confirm btn_confirm01">
	<a href="javascript:void(0);" onclick="form_rev_submit();" class="btn_update">확인</a>
	<?php if($view['ca_name'] == '상담') { ?>
	<!-- a href="javascript:void(0);" onclick="form_rev_copy();" class="btn_copy">문의글 생성</a -->
	<?php } ?>
<?php if ($view['wr_10'] == '답변요청중') { ?>
	<a href="#;" onclick="form_rev_save();return false;" >임시저장</a>
<?php } ?>
	<a href="javascript:void(0);" onclick="form_rev_del();" class="btn_delete">삭제</a>
    <a href="./qna2_list.php?<?php echo $qstr?>">목록</a>
    <a href="<?php echo G5_BBS_URL ?>/board.php?bo_table=little_work" data-fancybox data-type="iframe" data-src="<?php echo G5_BBS_URL ?>/board.php?bo_table=little_work">직원전달게시판</a>
</div>
</form>
<script type="text/javascript">
function form_rev_del()
{
	if(confirm('정말 삭제하시겠습니까?\n삭제한 내역은 복원할 수 없습니다.')) {
		$('#w').val('d');
		$('#form_rev').submit();
	}
}

function form_rev_copy()
{
	if(confirm('문의내역을 생성하시겠습니까?')) {
		$('#w').val('c');
		$('#form_rev').submit();
	}
}

/*
function form_rev_update()
{
	$('#w').val('u');
	$('#form_rev').submit();
}
*/
function form_rev_save()
{
	var f = $('#form_rev');

	<?php echo get_editor_js('wr_qna', $is_dhtml_editor); ?>

	<?php echo chk_editor_js('wr_qna', $is_dhtml_editor, '관리자답변'); ?>

	if($('#wr_qna_copy').is(':checked')) {

		<?php echo get_editor_js('wr_qna2', $is_dhtml_editor); ?>

		<?php echo chk_editor_js('wr_qna2', $is_dhtml_editor, '문의하기답변'); ?>
	}

	if(confirm('임시저장하시겠습니까?')) {
		$('#w').val('s');
		f.submit();
	}
}

function form_rev_submit()
{
	var f = $('#form_rev');

	<?php echo get_editor_js('wr_qna', $is_dhtml_editor); ?>

	<?php echo chk_editor_js('wr_qna', $is_dhtml_editor, '관리자답변'); ?>

	if($('#wr_qna_copy').is(':checked')) {

		<?php echo get_editor_js('wr_qna2', $is_dhtml_editor); ?>

		<?php echo chk_editor_js('wr_qna2', $is_dhtml_editor, '문의하기답변'); ?>
	}

	f.submit();
}

function content_view(wr_type, wr_id)
{
	var $cont = $('#'+wr_type+'_'+wr_id);
	($cont.is(':visible')) ? $cont.hide() : $cont.show();
}

$(function(){
	//상담하기
	var param_qna = 'actMode=counsel';
	param_qna += '&mb_id=<?php echo $mb['mb_id']?>';
	param_qna += '&wr_id=<?php echo $wr_id?>';
	param_qna += '&page_row=8';
	param_qna += '&page=';
	getAjaxList('pre_qna_list', param_qna, 'ajax.procList_new.php');

	//구매하기
	var param_buy = 'actMode=buylist';
	param_buy += '&mb_id=<?php echo $mb['mb_id']?>';
	param_buy += '&page_row=8';
	param_buy += '&page=';
	getAjaxList('pre_buy_list', param_buy, 'ajax.procList_new.php');
});
</script>

<?php
include_once(G5_ADMIN_PATH."/admin.tail.php");
?>
